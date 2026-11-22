import os
import sys
import json
import threading
import queue
import webrtcvad
import numpy as np
import pyaudio
from vosk import Model, KaldiRecognizer
import requests
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QWidget, 
                            QLabel, QPushButton, QComboBox, QTextEdit, 
                            QHBoxLayout, QCheckBox)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont

class AudioCaptureThread(threading.Thread):
    def __init__(self, sample_rate, channels, audio_queue, stop_event):
        super().__init__()
        self.sample_rate = sample_rate
        self.channels = channels
        self.audio_queue = audio_queue
        self.stop_event = stop_event
        self.p = pyaudio.PyAudio()
        
    def run(self):
        stream = self.p.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            input_device_index=self.get_speaker_device_index(),
            frames_per_buffer=4096
        )
        
        print(f"开始捕获音频，采样率: {self.sample_rate}, 声道数: {self.channels}")
        
        while not self.stop_event.is_set():
            data = stream.read(4096, exception_on_overflow=False)
            self.audio_queue.put(data)
        
        stream.stop_stream()
        stream.close()
        self.p.terminate()
        print("音频捕获线程已停止")
    
    def get_speaker_device_index(self):
        """获取扬声器的设备索引"""
        for i in range(self.p.get_device_count()):
            dev_info = self.p.get_device_info_by_index(i)
            # 查找输出设备(扬声器)
            if dev_info["maxOutputChannels"] > 0 and dev_info["hostApi"] == 0:
                return i
        return None

class SpeechRecognizer:
    def __init__(self, model_path=None, sample_rate=16000, online=False, proxy=None):
        self.sample_rate = sample_rate
        self.online = online
        self.proxy = proxy
        self.vad = webrtcvad.Vad(3)  # 语音活动检测，3为最激进模式
        
        if not online and model_path:
            print(f"加载离线模型: {model_path}")
            self.model = Model(model_path)
            self.recognizer = KaldiRecognizer(self.model, sample_rate)
        else:
            self.model = None
            self.recognizer = None
    
    def recognize(self, audio_data):
        if self.online:
            return self._recognize_online(audio_data)
        else:
            return self._recognize_offline(audio_data)
    
    def _recognize_offline(self, audio_data):
        if not self.recognizer:
            return ""
        
        # 转换为单声道16kHz PCM
        audio_array = np.frombuffer(audio_data, dtype=np.int16)
        if len(audio_array) == 0:
            return ""
        
        # 语音活动检测
        is_speech = self.vad.is_speech(audio_data, self.sample_rate)
        if not is_speech:
            return ""
        
        if self.recognizer.AcceptWaveform(audio_data):
            result = json.loads(self.recognizer.Result())
            return result.get("text", "")
        else:
            partial_result = json.loads(self.recognizer.PartialResult())
            return partial_result.get("partial", "")
    
    def _recognize_online(self, audio_data):
        try:
            # 这里使用百度API示例，实际使用时需要替换为你的API
            url = "http://vop.baidu.com/server_api"
            headers = {"Content-Type": "audio/pcm;rate=16000"}
            params = {
                "cuid": "speaker_to_text",
                "token": "your_token_here"  # 需要替换为实际的token
            }
            
            proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
            
            response = requests.post(
                url,
                params=params,
                data=audio_data,
                headers=headers,
                proxies=proxies
            )
            
            if response.status_code == 200:
                result = response.json()
                if result["err_no"] == 0:
                    return " ".join([x[""] for x in result["result"]])
        except Exception as e:
            print(f"在线识别错误: {e}")
        return ""

class SubtitleWindow(QMainWindow):
    update_signal = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("扬声器实时字幕转换")
        self.setGeometry(100, 100, 800, 600)
        
        # 初始化变量
        self.audio_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.capture_thread = None
        self.recognizer = None
        self.current_model = None
        self.sample_rate = 16000
        self.channels = 1
        self.online_mode = False
        
        # 初始化UI
        self.init_ui()
        
        # 连接信号
        self.update_signal.connect(self.update_subtitle)
        
        # 自动检测音频设备
        self.detect_audio_device()
        
    def init_ui(self):
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        
        # 标题
        title_label = QLabel("扬声器实时字幕转换")
        title_label.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)
        
        # 控制面板
        control_layout = QHBoxLayout()
        
        # 模型选择
        self.model_combo = QComboBox()
        self.model_combo.addItem("vosk-model-small-cn-0.22 (小模型)", "vosk-model-small-cn-0.22")
        self.model_combo.addItem("vosk-model-cn-0.22 (标准模型)", "vosk-model-cn-0.22")
        self.model_combo.addItem("vosk-model-cn-kaldi-multicn-0.15 (多方言模型)", "vosk-model-cn-kaldi-multicn-0.15")
        control_layout.addWidget(QLabel("选择模型:"))
        control_layout.addWidget(self.model_combo)
        
        # 在线识别复选框
        self.online_check = QCheckBox("使用在线识别")
        self.online_check.stateChanged.connect(self.toggle_online_mode)
        control_layout.addWidget(self.online_check)
        
        # 开始/停止按钮
        self.start_btn = QPushButton("开始")
        self.start_btn.clicked.connect(self.toggle_capture)
        control_layout.addWidget(self.start_btn)
        
        main_layout.addLayout(control_layout)
        
        # 字幕显示区域
        self.subtitle_display = QTextEdit()
        self.subtitle_display.setReadOnly(True)
        self.subtitle_display.setFont(QFont("Microsoft YaHei", 24))
        self.subtitle_display.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.subtitle_display, 1)
        
        # 状态栏
        self.status_label = QLabel("准备就绪")
        self.status_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.status_label)
        
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)
        
        # 定时器用于处理音频队列
        self.timer = QTimer()
        self.timer.timeout.connect(self.process_audio)
        self.timer.start(100)  # 每100ms处理一次
    
    def detect_audio_device(self):
        """检测音频设备并设置合适的采样率和声道数"""
        p = pyaudio.PyAudio()
        try:
            # 获取默认输出设备信息
            default_output = p.get_default_output_device_info()
            self.sample_rate = int(default_output["defaultSampleRate"])
            self.channels = min(2, default_output["maxOutputChannels"])  # 最多使用双声道
            
            self.status_label.setText(f"检测到音频设备: {default_output['name']}, 采样率: {self.sample_rate}Hz, 声道数: {self.channels}")
        except Exception as e:
            self.status_label.setText(f"音频设备检测失败: {str(e)}, 使用默认设置")
            self.sample_rate = 16000
            self.channels = 1
        finally:
            p.terminate()
    
    def toggle_online_mode(self, state):
        self.online_mode = state == Qt.Checked
        if self.online_mode:
            self.status_label.setText("已切换到在线识别模式")
        else:
            self.status_label.setText("已切换到离线识别模式")
    
    def toggle_capture(self):
        if self.capture_thread and self.capture_thread.is_alive():
            self.stop_capture()
            self.start_btn.setText("开始")
        else:
            self.start_capture()
            self.start_btn.setText("停止")
    
    def start_capture(self):
        if not self.online_mode:
            model_dir = self.model_combo.currentData()
            if not os.path.exists(model_dir):
                self.status_label.setText(f"错误: 模型目录 {model_dir} 不存在!")
                return
            
            self.current_model = model_dir
        
        self.stop_event.clear()
        
        # 创建识别器
        self.recognizer = SpeechRecognizer(
            model_path=self.current_model,
            sample_rate=self.sample_rate,
            online=self.online_mode,
            proxy="http://127.0.0.1:20808" if self.online_mode else None
        )
        
        # 创建音频捕获线程
        self.capture_thread = AudioCaptureThread(
            sample_rate=self.sample_rate,
            channels=self.channels,
            audio_queue=self.audio_queue,
            stop_event=self.stop_event
        )
        self.capture_thread.start()
        
        self.status_label.setText(f"正在捕获音频... 采样率: {self.sample_rate}Hz, 声道数: {self.channels}")
    
    def stop_capture(self):
        self.stop_event.set()
        if self.capture_thread:
            self.capture_thread.join()
        self.capture_thread = None
        self.recognizer = None
        self.status_label.setText("已停止捕获音频")
    
    def process_audio(self):
        if not self.recognizer or self.audio_queue.empty():
            return
        
        try:
            audio_data = self.audio_queue.get_nowait()
            text = self.recognizer.recognize(audio_data)
            
            if text:
                self.update_signal.emit(text)
        except queue.Empty:
            pass
    
    def update_subtitle(self, text):
        self.subtitle_display.setPlainText(text)
    
    def closeEvent(self, event):
        self.stop_capture()
        self.timer.stop()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SubtitleWindow()
    window.show()
    sys.exit(app.exec_())