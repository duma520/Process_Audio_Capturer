import os
import sys
import queue
import threading
import json
import pyaudio
import wave
import numpy as np
from vosk import Model, KaldiRecognizer
import requests
from urllib.parse import quote
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import webbrowser
from datetime import datetime

class AudioRecorder:
    def __init__(self):
        self.audio = pyaudio.PyAudio()
        self.stream = None
        self.frames = []
        self.is_recording = False
        self.channels = 2  # 默认立体声
        self.rate = 44100  # 默认采样率
        self.format = pyaudio.paInt16
        self.chunk = 1024
        self.device_index = None
        self.audio_queue = queue.Queue()
        
    def find_speaker_device(self):
        """查找扬声器设备"""
        host_api_count = self.audio.get_host_api_count()
        for i in range(host_api_count):
            host_api_info = self.audio.get_host_api_info_by_index(i)
            device_count = host_api_info.get('deviceCount', 0)
            for j in range(device_count):
                try:
                    device_info = self.audio.get_device_info_by_host_api_device_index(i, j)
                    # 检查是否是输出设备
                    if device_info.get('maxOutputChannels', 0) > 0:
                        # 优先选择支持立体声的设备
                        if device_info.get('maxOutputChannels', 0) >= 2:
                            self.channels = 2
                            self.device_index = j
                            self.rate = int(device_info.get('defaultSampleRate', 44100))
                            return
                except:
                    continue
        
        # 如果没有找到立体声设备，选择第一个输出设备
        for i in range(self.audio.get_device_count()):
            try:
                device_info = self.audio.get_device_info_by_index(i)
                if device_info.get('maxOutputChannels', 0) > 0:
                    self.channels = 1
                    self.device_index = i
                    self.rate = int(device_info.get('defaultSampleRate', 44100))
                    return
            except:
                continue
        
        # 如果还是没找到，使用默认设备
        self.device_index = self.audio.get_default_output_device_info().get('index')
        self.channels = 2
        self.rate = 44100

    def callback(self, in_data, frame_count, time_info, status):
        """音频回调函数"""
        self.audio_queue.put(in_data)
        return (None, pyaudio.paContinue)

    def start_recording(self):
        """开始录制扬声器音频"""
        self.find_speaker_device()
        
        if self.device_index is None:
            raise Exception("未找到可用的扬声器设备")
        
        self.stream = self.audio.open(
            format=self.format,
            channels=self.channels,
            rate=self.rate,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=self.chunk,
            stream_callback=self.callback,
            start=False
        )
        
        self.is_recording = True
        self.stream.start_stream()
        
    def stop_recording(self):
        """停止录制"""
        if self.stream is not None:
            self.is_recording = False
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None

    def get_audio_data(self):
        """从队列中获取音频数据"""
        try:
            return self.audio_queue.get_nowait()
        except queue.Empty:
            return None

class SpeechRecognizer:
    def __init__(self, model_path="vosk-model-small-cn-0.22"):
        self.offline_model = None
        self.offline_recognizer = None
        self.online_api_url = "http://127.0.0.1:20808"
        self.use_offline = True
        self.load_offline_model(model_path)
        
    def load_offline_model(self, model_path):
        """加载离线模型"""
        if os.path.exists(model_path):
            try:
                self.offline_model = Model(model_path)
                print(f"离线模型加载成功: {model_path}")
            except Exception as e:
                print(f"加载离线模型失败: {e}")
                self.offline_model = None
        else:
            print(f"离线模型目录不存在: {model_path}")
            self.offline_model = None
    
    def init_offline_recognizer(self, sample_rate, channels):
        """初始化离线识别器"""
        if self.offline_model:
            self.offline_recognizer = KaldiRecognizer(self.offline_model, sample_rate)
            self.offline_recognizer.SetWords(True)
    
    def recognize_offline(self, audio_data):
        """离线识别"""
        if self.offline_recognizer and audio_data:
            if self.offline_recognizer.AcceptWaveform(audio_data):
                result = json.loads(self.offline_recognizer.Result())
                return result.get("text", "")
            else:
                partial_result = json.loads(self.offline_recognizer.PartialResult())
                return partial_result.get("partial", "")
        return ""
    
    def recognize_online(self, audio_data):
        """在线识别（通过代理）"""
        if not audio_data:
            return ""
        
        try:
            # 将音频数据发送到在线API
            response = requests.post(
                f"{self.online_api_url}/recognize",
                files={"audio": ("audio.wav", audio_data)},
                timeout=5
            )
            if response.status_code == 200:
                result = response.json()
                return result.get("text", "")
        except Exception as e:
            print(f"在线识别失败: {e}")
        
        return ""

class Application(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("扬声器实时字幕转换")
        self.geometry("800x600")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        
        # 初始化组件
        self.init_ui()
        
        # 初始化音频和识别器
        self.recorder = AudioRecorder()
        self.recognizer = SpeechRecognizer()
        
        # 状态变量
        self.is_running = False
        self.last_text = ""
        self.accumulated_text = ""
        self.start_time = None
        
    def init_ui(self):
        """初始化用户界面"""
        # 主框架
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 控制面板
        control_frame = ttk.LabelFrame(main_frame, text="控制")
        control_frame.pack(fill=tk.X, pady=(0, 10))
        
        # 开始/停止按钮
        self.start_button = ttk.Button(control_frame, text="开始", command=self.start_captioning)
        self.start_button.pack(side=tk.LEFT, padx=5, pady=5)
        
        # 清除按钮
        self.clear_button = ttk.Button(control_frame, text="清除", command=self.clear_text)
        self.clear_button.pack(side=tk.LEFT, padx=5, pady=5)
        
        # 保存按钮
        self.save_button = ttk.Button(control_frame, text="保存", command=self.save_text)
        self.save_button.pack(side=tk.LEFT, padx=5, pady=5)
        
        # 识别模式选择
        self.recognition_mode = tk.StringVar(value="offline")
        ttk.Radiobutton(
            control_frame, 
            text="离线识别", 
            variable=self.recognition_mode, 
            value="offline"
        ).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(
            control_frame, 
            text="在线识别", 
            variable=self.recognition_mode, 
            value="online"
        ).pack(side=tk.LEFT, padx=5)
        
        # 状态信息
        self.status_label = ttk.Label(control_frame, text="就绪")
        self.status_label.pack(side=tk.RIGHT, padx=5)
        
        # 字幕显示区域
        self.subtitle_text = scrolledtext.ScrolledText(
            main_frame,
            wrap=tk.WORD,
            font=("Microsoft YaHei", 14),
            bg="black",
            fg="white"
        )
        self.subtitle_text.pack(fill=tk.BOTH, expand=True)
        
        # 版权信息
        ttk.Label(
            main_frame, 
            text="扬声器实时字幕转换 v1.0", 
            foreground="gray"
        ).pack(side=tk.BOTTOM, fill=tk.X)
    
    def start_captioning(self):
        """开始/停止字幕转换"""
        if not self.is_running:
            try:
                # 初始化识别器
                self.recognizer.use_offline = (self.recognition_mode.get() == "offline")
                self.recognizer.init_offline_recognizer(self.recorder.rate, self.recorder.channels)
                
                # 开始录制
                self.recorder.start_recording()
                self.is_running = True
                self.start_button.config(text="停止")
                self.status_label.config(text="正在转换字幕...")
                self.start_time = datetime.now()
                
                # 启动处理线程
                self.process_thread = threading.Thread(target=self.process_audio, daemon=True)
                self.process_thread.start()
                
                # 启动UI更新
                self.update_ui()
                
            except Exception as e:
                messagebox.showerror("错误", f"无法启动音频录制: {str(e)}")
                self.is_running = False
                self.start_button.config(text="开始")
                self.status_label.config(text="就绪")
        else:
            self.stop_captioning()
    
    def stop_captioning(self):
        """停止字幕转换"""
        self.is_running = False
        self.recorder.stop_recording()
        self.start_button.config(text="开始")
        
        if self.start_time:
            duration = datetime.now() - self.start_time
            self.status_label.config(text=f"已停止 - 运行时间: {duration}")
        else:
            self.status_label.config(text="已停止")
    
    def process_audio(self):
        """处理音频数据"""
        while self.is_running:
            audio_data = self.recorder.get_audio_data()
            if audio_data:
                # 转换为单声道（如果需要）
                if self.recorder.channels > 1:
                    audio_array = np.frombuffer(audio_data, dtype=np.int16)
                    audio_array = audio_array.reshape(-1, self.recorder.channels)
                    audio_array = audio_array.mean(axis=1).astype(np.int16)
                    audio_data = audio_array.tobytes()
                
                # 创建WAV格式的音频数据
                wav_data = self.create_wav_data(audio_data)
                
                # 识别语音
                if self.recognizer.use_offline:
                    text = self.recognizer.recognize_offline(wav_data)
                else:
                    text = self.recognizer.recognize_online(wav_data)
                
                if text and text != self.last_text:
                    self.last_text = text
                    self.accumulated_text += text + "\n"
    
    def create_wav_data(self, audio_data):
        """创建WAV格式的音频数据"""
        with wave.open("temp.wav", "wb") as wf:
            wf.setnchannels(1)  # 转换为单声道
            wf.setsampwidth(2)  # 16位
            wf.setframerate(self.recorder.rate)
            wf.writeframes(audio_data)
        
        with open("temp.wav", "rb") as f:
            return f.read()
    
    def update_ui(self):
        """更新UI"""
        if self.is_running:
            # 更新字幕显示
            self.subtitle_text.delete(1.0, tk.END)
            self.subtitle_text.insert(tk.END, self.accumulated_text)
            self.subtitle_text.see(tk.END)
            
            # 更新状态信息
            if self.start_time:
                duration = datetime.now() - self.start_time
                self.status_label.config(text=f"运行中 - 时长: {duration}")
            
            # 每100毫秒更新一次
            self.after(100, self.update_ui)
    
    def clear_text(self):
        """清除字幕文本"""
        self.accumulated_text = ""
        self.subtitle_text.delete(1.0, tk.END)
    
    def save_text(self):
        """保存字幕文本"""
        if not self.accumulated_text:
            messagebox.showwarning("警告", "没有可保存的字幕内容")
            return
        
        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(self.accumulated_text)
                messagebox.showinfo("成功", "字幕已保存")
            except Exception as e:
                messagebox.showerror("错误", f"保存文件失败: {str(e)}")
    
    def on_close(self):
        """关闭窗口时的处理"""
        if self.is_running:
            self.stop_captioning()
        self.destroy()

if __name__ == "__main__":
    # 检查Vosk模型是否存在
    if not os.path.exists("vosk-model-small-cn-0.22"):
        print("错误: 未找到Vosk中文模型目录 'vosk-model-small-cn-0.22'")
        print("请从 https://alphacephei.com/vosk/models 下载并解压到当前目录")
        input("按回车键退出...")
        sys.exit(1)
    
    # 检查PyAudio是否可用
    try:
        import pyaudio
    except ImportError:
        print("错误: 需要安装PyAudio库")
        print("可以通过 'pip install pyaudio' 安装")
        input("按回车键退出...")
        sys.exit(1)
    
    # 检查Vosk是否可用
    try:
        from vosk import Model, KaldiRecognizer
    except ImportError:
        print("错误: 需要安装Vosk库")
        print("可以通过 'pip install vosk' 安装")
        input("按回车键退出...")
        sys.exit(1)
    
    # 运行应用程序
    app = Application()
    app.mainloop()