import sys
import os
import json
import threading
import queue
import pyaudio
import wave
import requests
from vosk import Model, KaldiRecognizer
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QWidget, 
                            QLabel, QTextEdit, QPushButton, QComboBox, 
                            QCheckBox, QHBoxLayout, QMessageBox)
from PyQt5.QtCore import Qt, QTimer

class AudioRecorder:
    def __init__(self, model_path=None, proxy=None):
        self.audio = pyaudio.PyAudio()
        self.stream = None
        self.frames = []
        self.is_recording = False
        self.model_path = model_path
        self.proxy = proxy
        self.recognizer = None
        self.sample_rate = 16000
        self.channels = 1
        self.chunk = 1024
        
        if model_path and os.path.exists(model_path):
            self.model = Model(model_path)
        else:
            self.model = None
            
    def find_speaker_device(self):
        """查找扬声器设备"""
        device_index = None
        for i in range(self.audio.get_device_count()):
            dev_info = self.audio.get_device_info_by_index(i)
            # 查找输出设备(扬声器)且支持立体声
            if dev_info['maxOutputChannels'] > 0:
                if device_index is None or dev_info['maxInputChannels'] < dev_info['maxOutputChannels']:
                    device_index = i
                    self.sample_rate = int(dev_info['defaultSampleRate'])
                    self.channels = min(2, dev_info['maxOutputChannels'])
        return device_index
    
    def start_recording(self, callback):
        """开始录音"""
        device_index = self.find_speaker_device()
        if device_index is None:
            raise Exception("未找到扬声器设备")
            
        if self.model:
            self.recognizer = KaldiRecognizer(self.model, self.sample_rate)
            self.recognizer.SetWords(True)
        
        self.stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=self.chunk,
            stream_callback=callback
        )
        
        self.is_recording = True
        self.stream.start_stream()
        
    def stop_recording(self):
        """停止录音"""
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        self.is_recording = False
        
    def recognize_audio(self, data):
        """识别音频"""
        if self.recognizer and self.recognizer.AcceptWaveform(data):
            result = json.loads(self.recognizer.Result())
            return result.get('text', '')
        return None
    
    def online_recognize(self, data):
        """在线识别音频"""
        if not self.proxy:
            return None
            
        # 这里需要实现在线识别的API调用
        # 由于没有具体的API信息，这里只是示例
        try:
            headers = {'Content-Type': 'audio/wav'}
            proxies = {'http': self.proxy, 'https': self.proxy}
            response = requests.post('https://api.example.com/speech', 
                                   data=data, headers=headers, proxies=proxies)
            if response.status_code == 200:
                return response.json().get('text', '')
        except Exception as e:
            print(f"在线识别错误: {e}")
        return None

class SubtitleApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.recorder = None
        self.text_queue = queue.Queue()
        self.init_ui()
        
    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle('扬声器实时字幕转换')
        self.setGeometry(100, 100, 600, 400)
        
        main_widget = QWidget()
        layout = QVBoxLayout()
        
        # 标题
        title_label = QLabel('扬声器实时字幕转换')
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet('font-size: 20px; font-weight: bold;')
        layout.addWidget(title_label)
        
        # 字幕显示区域
        self.subtitle_display = QTextEdit()
        self.subtitle_display.setReadOnly(True)
        self.subtitle_display.setStyleSheet('font-size: 16px;')
        layout.addWidget(self.subtitle_display, 1)
        
        # 控制区域
        control_layout = QHBoxLayout()
        
        self.start_btn = QPushButton('开始')
        self.start_btn.clicked.connect(self.start_recording)
        control_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton('停止')
        self.stop_btn.clicked.connect(self.stop_recording)
        self.stop_btn.setEnabled(False)
        control_layout.addWidget(self.stop_btn)
        
        self.clear_btn = QPushButton('清空')
        self.clear_btn.clicked.connect(self.clear_text)
        control_layout.addWidget(self.clear_btn)
        
        layout.addLayout(control_layout)
        
        # 设置区域
        settings_layout = QHBoxLayout()
        
        self.online_check = QCheckBox('使用在线识别')
        settings_layout.addWidget(self.online_check)
        
        self.model_status = QLabel('离线模型: 已加载' if os.path.exists('vosk-model-small-cn-0.22') else '离线模型: 未找到')
        settings_layout.addWidget(self.model_status)
        
        layout.addLayout(settings_layout)
        
        main_widget.setLayout(layout)
        self.setCentralWidget(main_widget)
        
        # 定时器检查队列中的新文本
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_subtitle)
        self.timer.start(100)
        
    def audio_callback(self, in_data, frame_count, time_info, status):
        """音频回调函数"""
        if self.recorder and self.recorder.is_recording:
            text = None
            
            # 离线识别
            if not self.online_check.isChecked() and self.recorder.model:
                text = self.recorder.recognize_audio(in_data)
            # 在线识别
            elif self.online_check.isChecked():
                text = self.recorder.online_recognize(in_data)
                
            if text:
                self.text_queue.put(text)
                
        return (in_data, pyaudio.paContinue)
        
    def start_recording(self):
        """开始录音"""
        try:
            model_path = 'vosk-model-small-cn-0.22'
            proxy = 'http://127.0.0.1:20808' if self.online_check.isChecked() else None
            
            self.recorder = AudioRecorder(model_path=model_path, proxy=proxy)
            self.recorder.start_recording(self.audio_callback)
            
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.online_check.setEnabled(False)
            
        except Exception as e:
            QMessageBox.critical(self, '错误', f'无法开始录音: {str(e)}')
            
    def stop_recording(self):
        """停止录音"""
        if self.recorder:
            self.recorder.stop_recording()
            
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.online_check.setEnabled(True)
        
    def clear_text(self):
        """清空字幕"""
        self.subtitle_display.clear()
        
    def update_subtitle(self):
        """更新字幕显示"""
        while not self.text_queue.empty():
            text = self.text_queue.get()
            self.subtitle_display.append(text)
            
    def closeEvent(self, event):
        """关闭窗口事件"""
        if self.recorder and self.recorder.is_recording:
            self.stop_recording()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # 检查Vosk模型是否存在
    if not os.path.exists('vosk-model-small-cn-0.22'):
        reply = QMessageBox.question(None, '模型未找到', 
                                   '未找到离线模型(vosk-model-small-cn-0.22)，是否继续使用在线识别?', 
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.No:
            sys.exit()
    
    window = SubtitleApp()
    window.show()
    sys.exit(app.exec_())