import sys
import threading
import queue
import pyaudio
import speech_recognition as sr
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QWidget, 
                            QTextEdit, QPushButton, QLabel, QComboBox, QHBoxLayout)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont

class AudioTranscriberApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("实时音频转文字工具")
        self.setGeometry(100, 100, 800, 600)
        
        # 初始化语音识别器
        self.recognizer = sr.Recognizer()
        self.audio_queue = queue.Queue()
        self.stop_listening = None
        self.is_listening = False
        self.current_device_index = None
        
        # 初始化UI
        self.init_ui()
        
        # 获取音频设备列表
        self.update_audio_devices()
        
    def init_ui(self):
        # 主窗口部件
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout()
        main_widget.setLayout(layout)
        
        # 标题
        title_label = QLabel("实时音频转文字工具")
        title_label.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # 设备选择区域
        device_layout = QHBoxLayout()
        device_label = QLabel("选择音频输入设备:")
        device_label.setFont(QFont("Microsoft YaHei", 10))
        self.device_combo = QComboBox()
        self.device_combo.setFont(QFont("Microsoft YaHei", 10))
        refresh_btn = QPushButton("刷新设备")
        refresh_btn.setFont(QFont("Microsoft YaHei", 10))
        refresh_btn.clicked.connect(self.update_audio_devices)
        
        device_layout.addWidget(device_label)
        device_layout.addWidget(self.device_combo)
        device_layout.addWidget(refresh_btn)
        layout.addLayout(device_layout)
        
        # 文本显示区域
        self.text_display = QTextEdit()
        self.text_display.setFont(QFont("Microsoft YaHei", 12))
        self.text_display.setReadOnly(True)
        layout.addWidget(self.text_display)
        
        # 控制按钮区域
        control_layout = QHBoxLayout()
        self.start_btn = QPushButton("开始监听")
        self.start_btn.setFont(QFont("Microsoft YaHei", 12))
        self.start_btn.clicked.connect(self.toggle_listening)
        
        clear_btn = QPushButton("清空文本")
        clear_btn.setFont(QFont("Microsoft YaHei", 12))
        clear_btn.clicked.connect(self.clear_text)
        
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(clear_btn)
        layout.addLayout(control_layout)
        
        # 状态栏
        self.status_label = QLabel("准备就绪")
        self.status_label.setFont(QFont("Microsoft YaHei", 10))
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)
        
        # 设置定时器处理音频队列
        self.timer = QTimer()
        self.timer.timeout.connect(self.process_audio_queue)
        self.timer.start(100)  # 每100毫秒检查一次队列
        
    def update_audio_devices(self):
        self.device_combo.clear()
        p = pyaudio.PyAudio()
        device_count = p.get_device_count()
        
        for i in range(device_count):
            device_info = p.get_device_info_by_index(i)
            if device_info["maxInputChannels"] > 0:
                self.device_combo.addItem(device_info["name"], userData=i)
        
        p.terminate()
        
        if self.device_combo.count() > 0:
            self.status_label.setText(f"找到 {self.device_combo.count()} 个音频输入设备")
        else:
            self.status_label.setText("未找到音频输入设备")
    
    def toggle_listening(self):
        if self.is_listening:
            self.stop_listening()
            self.is_listening = False
            self.start_btn.setText("开始监听")
            self.status_label.setText("已停止监听")
        else:
            selected_index = self.device_combo.currentIndex()
            if selected_index >= 0:
                self.current_device_index = self.device_combo.itemData(selected_index)
                self.start_listening()
                self.is_listening = True
                self.start_btn.setText("停止监听")
                self.status_label.setText("正在监听...")
            else:
                self.status_label.setText("请先选择音频输入设备")
    
    def start_listening(self):
        def callback(recognizer, audio):
            self.audio_queue.put(audio)
        
        self.stop_listening = self.recognizer.listen_in_background(
            sr.Microphone(device_index=self.current_device_index),
            callback,
            phrase_time_limit=5
        )
    
    def process_audio_queue(self):
        while not self.audio_queue.empty():
            audio = self.audio_queue.get()
            try:
                text = self.recognizer.recognize_google(audio, language="zh-CN")
                self.append_text(text)
            except sr.UnknownValueError:
                self.append_text("(无法识别的音频)")
            except sr.RequestError as e:
                self.append_text(f"(识别服务错误: {str(e)})")
            except Exception as e:
                self.append_text(f"(错误: {str(e)})")
    
    def append_text(self, text):
        self.text_display.moveCursor(QtGui.QTextCursor.End)
        self.text_display.insertPlainText(text + "\n")
        self.text_display.ensureCursorVisible()
    
    def clear_text(self):
        self.text_display.clear()
    
    def closeEvent(self, event):
        if self.is_listening:
            self.stop_listening()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AudioTranscriberApp()
    window.show()
    sys.exit(app.exec_())