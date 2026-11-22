import os
import sys
import queue
import threading
import json
import wave
import pyaudio
from vosk import Model, KaldiRecognizer
import requests
import urllib.parse
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import sounddevice as sd
import numpy as np
import webbrowser

class AudioRecorder:
    def __init__(self):
        self.audio = pyaudio.PyAudio()
        self.stream = None
        self.frames = []
        self.is_recording = False
        self.sample_rate = 16000
        self.channels = 1
        self.format = pyaudio.paInt16
        self.chunk = 1024

    def start_recording(self):
        self.frames = []
        self.is_recording = True
        
        # 打开扬声器流 (loopback)
        self.stream = self.audio.open(
            format=self.format,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.chunk,
            input_device_index=self.get_loopback_device(),
            stream_callback=self.callback
        )
        
        self.stream.start_stream()

    def stop_recording(self):
        self.is_recording = False
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        self.stream = None

    def get_loopback_device(self):
        """获取扬声器(loopback)设备索引"""
        for i in range(self.audio.get_device_count()):
            dev_info = self.audio.get_device_info_by_index(i)
            # 查找名称中包含"立体声混音"或"Loopback"的设备
            if "立体声混音" in dev_info["name"] or "Loopback" in dev_info["name"]:
                print(f"找到扬声器设备: {dev_info['name']}")
                return i
        # 如果找不到特定设备，尝试使用默认输入设备
        return self.audio.get_default_input_device_info()["index"]

    def callback(self, in_data, frame_count, time_info, status):
        if self.is_recording:
            self.frames.append(in_data)
        return (in_data, pyaudio.paContinue)

    def get_audio_data(self):
        return b''.join(self.frames)

class SpeechToTextApp:
    def __init__(self, root):
        self.root = root
        self.root.title("扬声器实时字幕转换")
        
        # 初始化变量
        self.audio_recorder = AudioRecorder()
        self.audio_queue = queue.Queue()
        self.text_queue = queue.Queue()
        self.is_running = False
        self.use_online = False
        self.proxy = {"http": "http://127.0.0.1:20808"}
        self.current_model = None
        self.available_models = self.detect_local_models()
        
        # 创建GUI
        self.create_widgets()
        
        # 设置默认模型
        if self.available_models:
            self.model_combobox.set(self.available_models[0])
        
        # 启动处理线程
        self.process_thread = threading.Thread(target=self.process_audio, daemon=True)
        self.process_thread.start()
        
        # 启动UI更新线程
        self.update_ui()

    def detect_local_models(self):
        """检测本地可用的Vosk模型"""
        models = []
        model_dirs = [
            "vosk-model-cn-0.22",
            "vosk-model-cn-kaldi-multicn-0.15", 
            "vosk-model-small-cn-0.22"
        ]
        
        for dir_name in model_dirs:
            if os.path.exists(dir_name):
                models.append(dir_name)
        
        return models

    def create_widgets(self):
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 模型选择
        ttk.Label(main_frame, text="选择模型:").grid(row=0, column=0, sticky=tk.W)
        self.model_combobox = ttk.Combobox(main_frame, values=self.available_models, state="readonly")
        self.model_combobox.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5)
        
        # 识别模式
        self.mode_var = tk.StringVar(value="offline")
        ttk.Radiobutton(main_frame, text="离线识别", variable=self.mode_var, value="offline").grid(row=1, column=0, sticky=tk.W)
        ttk.Radiobutton(main_frame, text="在线识别", variable=self.mode_var, value="online").grid(row=1, column=1, sticky=tk.W)
        
        # 字幕显示区域
        ttk.Label(main_frame, text="实时字幕:").grid(row=2, column=0, sticky=tk.W, pady=(10, 0))
        self.subtitle_text = tk.Text(main_frame, height=10, width=50, wrap=tk.WORD)
        self.subtitle_text.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # 控制按钮
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=4, column=0, columnspan=2, pady=(10, 0))
        
        self.start_button = ttk.Button(button_frame, text="开始", command=self.start_capture)
        self.start_button.pack(side=tk.LEFT, padx=5)
        
        self.stop_button = ttk.Button(button_frame, text="停止", command=self.stop_capture, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)
        
        self.clear_button = ttk.Button(button_frame, text="清屏", command=self.clear_text)
        self.clear_button.pack(side=tk.LEFT, padx=5)
        
        # 状态栏
        self.status_var = tk.StringVar(value="准备就绪")
        ttk.Label(main_frame, textvariable=self.status_var).grid(row=5, column=0, columnspan=2, sticky=tk.W)
        
        # 配置行列权重
        main_frame.columnconfigure(1, weight=1)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

    def start_capture(self):
        if not self.available_models and self.mode_var.get() == "offline":
            messagebox.showerror("错误", "没有找到本地模型且选择了离线模式！")
            return
        
        self.is_running = True
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        
        # 初始化语音识别器
        if self.mode_var.get() == "offline":
            model_path = self.model_combobox.get()
            try:
                self.current_model = Model(model_path)
                self.status_var.set(f"使用离线模型: {model_path}")
            except Exception as e:
                messagebox.showerror("错误", f"加载模型失败: {str(e)}")
                self.stop_capture()
                return
        else:
            self.status_var.set("使用在线识别服务")
        
        # 开始录音
        self.audio_recorder.start_recording()
        
        # 清空队列
        while not self.audio_queue.empty():
            self.audio_queue.get()
        while not self.text_queue.empty():
            self.text_queue.get()

    def stop_capture(self):
        self.is_running = False
        self.audio_recorder.stop_recording()
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.status_var.set("已停止")

    def clear_text(self):
        self.subtitle_text.delete(1.0, tk.END)

    def process_audio(self):
        recognizer = None
        
        while True:
            if not self.is_running:
                recognizer = None
                continue
            
            # 获取音频数据
            audio_data = self.audio_recorder.get_audio_data()
            if not audio_data:
                continue
            
            # 离线识别
            if self.mode_var.get() == "offline" and self.current_model:
                if recognizer is None:
                    recognizer = KaldiRecognizer(self.current_model, 16000)
                    recognizer.SetWords(True)
                
                if recognizer.AcceptWaveform(audio_data):
                    result = json.loads(recognizer.Result())
                    if 'text' in result and result['text']:
                        self.text_queue.put(result['text'])
            
            # 在线识别
            elif self.mode_var.get() == "online":
                try:
                    # 保存临时音频文件
                    with wave.open("temp.wav", "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(16000)
                        wf.writeframes(audio_data)
                    
                    # 发送到在线API (示例API，实际使用时需要替换)
                    with open("temp.wav", "rb") as audio_file:
                        response = requests.post(
                            "https://api.example.com/speech-to-text",
                            files={"audio": audio_file},
                            proxies=self.proxy
                        )
                    
                    if response.status_code == 200:
                        result = response.json()
                        if 'text' in result and result['text']:
                            self.text_queue.put(result['text'])
                
                except Exception as e:
                    self.status_var.set(f"在线识别错误: {str(e)}")
            
            # 清空音频缓冲区
            self.audio_recorder.frames = []

    def update_ui(self):
        # 更新字幕显示
        while not self.text_queue.empty():
            text = self.text_queue.get()
            timestamp = datetime.now().strftime("[%H:%M:%S] ")
            self.subtitle_text.insert(tk.END, timestamp + text + "\n")
            self.subtitle_text.see(tk.END)
        
        # 定期检查
        self.root.after(100, self.update_ui)

    def on_closing(self):
        self.is_running = False
        self.audio_recorder.stop_recording()
        self.root.destroy()

def main():
    root = tk.Tk()
    app = SpeechToTextApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()