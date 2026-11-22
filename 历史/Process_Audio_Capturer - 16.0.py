import os
import sys
import json
import threading
import queue
import requests
import pyaudio
import wave
import numpy as np
from vosk import Model, KaldiRecognizer
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QLabel, QPushButton, QTextEdit, QComboBox, 
                             QHBoxLayout, QMessageBox, QCheckBox)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QFont

class SignalEmitter(QObject):
    new_text = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)

class AudioRecorder:
    def __init__(self, emitter):
        self.emitter = emitter
        self.audio = pyaudio.PyAudio()
        self.stream = None
        self.frames = []
        self.recording = False
        self.channels = 2  # 默认立体声
        self.sample_rate = 44100  # 默认采样率
        self.format = pyaudio.paInt16
        self.chunk = 4096
        self.device_index = None
        self.find_speaker_device()
        
    def find_speaker_device(self):
        """查找扬声器输出设备"""
        info = self.audio.get_host_api_info_by_index(0)
        num_devices = info.get('deviceCount')
        
        for i in range(num_devices):
            device_info = self.audio.get_device_info_by_host_api_device_index(0, i)
            # 检查设备是否是输出设备且有足够多的通道
            if device_info.get('maxOutputChannels') > 0:
                self.device_index = i
                self.channels = min(8, device_info.get('maxOutputChannels'))
                self.sample_rate = int(device_info.get('defaultSampleRate'))
                self.emitter.status_signal.emit(f"找到扬声器设备: {device_info.get('name')}, 声道数: {self.channels}, 采样率: {self.sample_rate}")
                return
                
        self.emitter.error_signal.emit("未找到可用的扬声器输出设备!")
        self.device_index = None

    def start_recording(self):
        if self.device_index is None:
            self.emitter.error_signal.emit("没有可用的录音设备!")
            return False
            
        try:
            self.stream = self.audio.open(
                format=self.format,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                input_device_index=self.device_index,
                frames_per_buffer=self.chunk,
                stream_callback=self.callback
            )
            self.recording = True
            self.emitter.status_signal.emit(f"开始录制: {self.channels}声道, {self.sample_rate}Hz")
            return True
        except Exception as e:
            self.emitter.error_signal.emit(f"启动录音失败: {str(e)}")
            return False

    def stop_recording(self):
        self.recording = False
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        self.emitter.status_signal.emit("录制已停止")

    def callback(self, in_data, frame_count, time_info, status):
        if self.recording:
            self.frames.append(in_data)
        return (in_data, pyaudio.paContinue)

    def get_audio_data(self):
        if len(self.frames) > 0:
            data = b''.join(self.frames)
            self.frames = []
            return data
        return None

class SpeechRecognizer:
    def __init__(self, emitter, model_path="vosk-model-small-cn-0.22"):
        self.emitter = emitter
        self.offline_model = None
        self.offline_recognizer = None
        self.online_mode = False
        self.proxy = {"http": "http://127.0.0.1:20808", "https": "http://127.0.0.1:20808"}
        self.load_offline_model(model_path)
        self.audio_queue = queue.Queue()
        self.processing = False
        
    def load_offline_model(self, model_path):
        try:
            if os.path.exists(model_path):
                self.offline_model = Model(model_path)
                self.emitter.status_signal.emit(f"离线模型加载成功: {model_path}")
            else:
                self.emitter.error_signal.emit(f"离线模型目录不存在: {model_path}")
                self.offline_model = None
        except Exception as e:
            self.emitter.error_signal.emit(f"加载离线模型失败: {str(e)}")
            self.offline_model = None
            
    def set_online_mode(self, online):
        self.online_mode = online
        status = "在线" if online else "离线"
        self.emitter.status_signal.emit(f"切换识别模式: {status}")

    def recognize_online(self, audio_data, sample_rate):
        try:
            url = "https://api.example.com/speech-recognition"  # 替换为实际的API端点
            files = {'audio': ('audio.wav', audio_data, 'audio/wav')}
            response = requests.post(url, files=files, proxies=self.proxy, timeout=10)
            if response.status_code == 200:
                result = response.json()
                return result.get("text", "")
            else:
                self.emitter.error_signal.emit(f"在线识别失败: {response.status_code}")
                return ""
        except Exception as e:
            self.emitter.error_signal.emit(f"在线识别错误: {str(e)}")
            return ""

    def recognize_offline(self, audio_data, sample_rate):
        if not self.offline_model:
            return ""
            
        if not hasattr(self, 'offline_recognizer') or self.offline_recognizer is None:
            self.offline_recognizer = KaldiRecognizer(self.offline_model, sample_rate)
            self.offline_recognizer.SetWords(True)
            
        if self.offline_recognizer.AcceptWaveform(audio_data):
            result = json.loads(self.offline_recognizer.Result())
            return result.get("text", "")
        return ""

    def process_audio(self, audio_data, sample_rate, channels):
        try:
            # 将多声道转换为单声道
            if channels > 1:
                audio_array = np.frombuffer(audio_data, dtype=np.int16)
                audio_array = audio_array.reshape(-1, channels)
                audio_data = audio_array.mean(axis=1).astype(np.int16).tobytes()
                
            # 创建临时WAV文件数据
            with wave.open('temp.wav', 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(audio_data)
                
            with open('temp.wav', 'rb') as f:
                wav_data = f.read()
                
            if self.online_mode and not self.offline_model:
                text = self.recognize_online(wav_data, sample_rate)
            else:
                text = self.recognize_offline(wav_data, sample_rate)
                
            if text:
                self.emitter.new_text.emit(text)
                
        except Exception as e:
            self.emitter.error_signal.emit(f"音频处理错误: {str(e)}")

    def add_to_queue(self, audio_data, sample_rate, channels):
        self.audio_queue.put((audio_data, sample_rate, channels))
        if not self.processing:
            self.start_processing()

    def start_processing(self):
        self.processing = True
        threading.Thread(target=self.process_queue, daemon=True).start()

    def process_queue(self):
        while not self.audio_queue.empty():
            audio_data, sample_rate, channels = self.audio_queue.get()
            self.process_audio(audio_data, sample_rate, channels)
        self.processing = False

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("扬声器实时字幕转换")
        self.setGeometry(100, 100, 800, 600)
        
        self.signal_emitter = SignalEmitter()
        self.audio_recorder = AudioRecorder(self.signal_emitter)
        self.speech_recognizer = SpeechRecognizer(self.signal_emitter)
        
        self.init_ui()
        self.connect_signals()
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_audio)
        self.timer.start(100)  # 每100毫秒检查一次音频数据
        
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout()
        central_widget.setLayout(layout)
        
        # 状态栏
        self.status_label = QLabel("准备就绪")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(self.status_label)
        
        # 字幕显示区域
        self.subtitle_display = QTextEdit()
        self.subtitle_display.setReadOnly(True)
        self.subtitle_display.setFont(QFont("Microsoft YaHei", 24))
        self.subtitle_display.setAlignment(Qt.AlignCenter)
        self.subtitle_display.setStyleSheet("background-color: #222; color: #fff; border-radius: 10px; padding: 20px;")
        layout.addWidget(self.subtitle_display, 1)
        
        # 控制面板
        control_layout = QHBoxLayout()
        
        self.start_button = QPushButton("开始监听")
        self.start_button.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; padding: 10px; }")
        control_layout.addWidget(self.start_button)
        
        self.stop_button = QPushButton("停止监听")
        self.stop_button.setStyleSheet("QPushButton { background-color: #F44336; color: white; padding: 10px; }")
        self.stop_button.setEnabled(False)
        control_layout.addWidget(self.stop_button)
        
        self.clear_button = QPushButton("清除字幕")
        self.clear_button.setStyleSheet("QPushButton { background-color: #2196F3; color: white; padding: 10px; }")
        control_layout.addWidget(self.clear_button)
        
        layout.addLayout(control_layout)
        
        # 设置面板
        settings_layout = QHBoxLayout()
        
        self.online_checkbox = QCheckBox("在线识别模式")
        self.online_checkbox.setStyleSheet("color: #333;")
        settings_layout.addWidget(self.online_checkbox)
        
        layout.addLayout(settings_layout)
        
        # 底部信息
        info_label = QLabel("扬声器实时字幕转换 v1.0 | 优先使用离线模型")
        info_label.setAlignment(Qt.AlignCenter)
        info_label.setStyleSheet("color: #999; font-size: 10px;")
        layout.addWidget(info_label)
        
    def connect_signals(self):
        self.start_button.clicked.connect(self.start_listening)
        self.stop_button.clicked.connect(self.stop_listening)
        self.clear_button.clicked.connect(self.clear_subtitles)
        self.online_checkbox.stateChanged.connect(self.toggle_online_mode)
        
        self.signal_emitter.new_text.connect(self.update_subtitle)
        self.signal_emitter.error_signal.connect(self.show_error)
        self.signal_emitter.status_signal.connect(self.update_status)
        
    def start_listening(self):
        if self.audio_recorder.start_recording():
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.online_checkbox.setEnabled(False)
            
    def stop_listening(self):
        self.audio_recorder.stop_recording()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.online_checkbox.setEnabled(True)
        
    def clear_subtitles(self):
        self.subtitle_display.clear()
        
    def toggle_online_mode(self, state):
        self.speech_recognizer.set_online_mode(state == Qt.Checked)
        
    def update_audio(self):
        if self.audio_recorder.recording:
            audio_data = self.audio_recorder.get_audio_data()
            if audio_data:
                self.speech_recognizer.add_to_queue(
                    audio_data, 
                    self.audio_recorder.sample_rate, 
                    self.audio_recorder.channels
                )
                
    def update_subtitle(self, text):
        self.subtitle_display.append(text)
        self.subtitle_display.verticalScrollBar().setValue(
            self.subtitle_display.verticalScrollBar().maximum()
        )
        
    def show_error(self, message):
        QMessageBox.critical(self, "错误", message)
        
    def update_status(self, message):
        self.status_label.setText(message)
        
    def closeEvent(self, event):
        self.audio_recorder.stop_recording()
        if hasattr(self.audio_recorder, 'audio'):
            self.audio_recorder.audio.terminate()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec_())