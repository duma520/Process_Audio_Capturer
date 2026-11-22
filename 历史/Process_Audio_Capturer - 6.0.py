import sys
import queue
import sounddevice as sd
import speech_recognition as sr
import numpy as np
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QWidget, 
                            QTextEdit, QPushButton, QLabel, QComboBox, QHBoxLayout,
                            QMessageBox)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QTextCursor

class SystemAudioTranscriber(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("系统声音转文字工具")
        self.setGeometry(100, 100, 800, 600)
        
        # 初始化语音识别器
        self.recognizer = sr.Recognizer()
        self.audio_queue = queue.Queue()
        self.is_listening = False
        self.stream = None
        
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
        title_label = QLabel("系统声音转文字工具")
        title_label.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # 设备选择区域
        device_layout = QHBoxLayout()
        device_label = QLabel("选择音频设备:")
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
        
        # 添加帮助按钮
        help_btn = QPushButton("如何设置虚拟音频设备?")
        help_btn.setFont(QFont("Microsoft YaHei", 10))
        help_btn.clicked.connect(self.show_help)
        layout.addWidget(help_btn)
        
        # 文本显示区域
        self.text_display = QTextEdit()
        self.text_display.setFont(QFont("Microsoft YaHei", 12))
        self.text_display.setReadOnly(True)
        layout.addWidget(self.text_display)
        
        # 控制按钮区域
        control_layout = QHBoxLayout()
        self.start_btn = QPushButton("开始捕获")
        self.start_btn.setFont(QFont("Microsoft YaHei", 12))
        self.start_btn.clicked.connect(self.toggle_listening)
        self.start_btn.setEnabled(False)  # 默认禁用，直到选择设备
        
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
        self.timer.start(100)
        
    def show_help(self):
        help_text = """
        <h3>如何设置虚拟音频设备?</h3>
        <p>要捕获系统声音，您需要安装虚拟音频设备:</p>
        <ul>
            <li><b>Windows:</b> 安装 VB-Cable 或 Voicemeeter</li>
            <li><b>macOS:</b> 安装 BlackHole</li>
            <li><b>Linux:</b> 配置 PulseAudio 的 module-loopback</li>
        </ul>
        <p>安装后，请选择对应的虚拟设备作为输入设备。</p>
        """
        QMessageBox.information(self, "帮助信息", help_text)
    
    def update_audio_devices(self):
        self.device_combo.clear()
        self.start_btn.setEnabled(False)
        
        try:
            devices = sd.query_devices()
            hostapis = sd.query_hostapis()
            
            # 先尝试查找Loopback设备
            loopback_devices = []
            for i, device in enumerate(devices):
                if ('Loopback' in device['name'] or 
                    '立体声混音' in device['name'] or 
                    'Virtual Cable' in device['name']):
                    hostapi_name = hostapis[device['hostapi']]['name']
                    loopback_devices.append((i, f"{device['name']} ({hostapi_name})"))
            
            # 如果没有找到Loopback设备，则显示所有输入设备
            if not loopback_devices:
                for i, device in enumerate(devices):
                    if device['max_input_channels'] > 0:
                        hostapi_name = hostapis[device['hostapi']]['name']
                        self.device_combo.addItem(f"{device['name']} ({hostapi_name})", userData=i)
            else:
                for i, name in loopback_devices:
                    self.device_combo.addItem(name, userData=i)
            
            if self.device_combo.count() > 0:
                self.status_label.setText(f"找到 {self.device_combo.count()} 个音频设备")
                self.start_btn.setEnabled(True)
            else:
                self.status_label.setText("未找到可用的音频设备")
                self.show_help()
                
        except Exception as e:
            self.status_label.setText(f"获取设备列表失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"无法获取音频设备列表:\n{str(e)}")
    
    def toggle_listening(self):
        if self.is_listening:
            self.stop_recording()
            self.is_listening = False
            self.start_btn.setText("开始捕获")
            self.status_label.setText("已停止捕获")
        else:
            selected_index = self.device_combo.currentIndex()
            if selected_index >= 0:
                try:
                    self.start_recording()
                    self.is_listening = True
                    self.start_btn.setText("停止捕获")
                    self.status_label.setText("正在捕获系统声音...")
                except Exception as e:
                    self.status_label.setText(f"启动失败: {str(e)}")
                    QMessageBox.warning(self, "错误", f"无法开始捕获音频:\n{str(e)}")
            else:
                self.status_label.setText("请先选择音频设备")
    
    def start_recording(self):
        device_index = self.device_combo.currentData()
        device_info = sd.query_devices(device_index)
        
        # 自动选择合适的采样率和通道数
        samplerate = int(device_info.get('default_samplerate', 44100))
        channels = min(2, device_info.get('max_input_channels', 1))
        
        def audio_callback(indata, frames, time, status):
            if status:
                print(status)
            audio_data = (indata * 32767).astype(np.int16).tobytes()
            audio = sr.AudioData(audio_data, samplerate, channels)
            self.audio_queue.put(audio)
        
        self.stream = sd.InputStream(
            device=device_index,
            channels=channels,
            samplerate=samplerate,
            callback=audio_callback,
            blocksize=4096
        )
        self.stream.start()
    
    def stop_recording(self):
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except:
                pass
            finally:
                self.stream = None
    
    def process_audio_queue(self):
        while not self.audio_queue.empty():
            audio = self.audio_queue.get()
            try:
                text = self.recognizer.recognize_google(audio, language="zh-CN")
                self.append_text(text)
            except sr.UnknownValueError:
                pass
            except sr.RequestError as e:
                self.append_text(f"(识别服务错误: {str(e)})")
            except Exception as e:
                self.append_text(f"(错误: {str(e)})")
    
    def append_text(self, text):
        self.text_display.moveCursor(QTextCursor.End)
        self.text_display.insertPlainText(text + "\n")
        self.text_display.ensureCursorVisible()
    
    def clear_text(self):
        self.text_display.clear()
    
    def closeEvent(self, event):
        if self.is_listening:
            self.stop_recording()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SystemAudioTranscriber()
    window.show()
    sys.exit(app.exec_())