import sys
import threading
import queue
import time
import pyaudio
import speech_recognition as sr
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QWidget, 
                            QLabel, QPushButton, QTextEdit, QComboBox, 
                            QHBoxLayout, QSpinBox, QSizePolicy)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QPalette

class AudioTranscriber(QMainWindow):
    update_signal = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.recognizer = sr.Recognizer()
        self.audio_queue = queue.Queue()
        self.is_listening = False
        self.audio_stream = None
        self.pyaudio_instance = pyaudio.PyAudio()
        self.current_text = ""
        self.init_ui()
        self.update_signal.connect(self.update_display)
        
    def init_ui(self):
        """初始化用户界面"""
        self.setWindowTitle('实时音频转字幕工具')
        self.setGeometry(100, 100, 800, 400)
        
        # 主窗口部件
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        
        # 标题
        title_label = QLabel('实时音频转字幕')
        title_label.setFont(QFont('Arial', 18, QFont.Bold))
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # 控制面板
        control_layout = QHBoxLayout()
        
        # 设备选择
        self.device_combo = QComboBox()
        self.populate_audio_devices()
        control_layout.addWidget(QLabel('音频设备:'))
        control_layout.addWidget(self.device_combo)
        
        # 语言选择
        self.language_combo = QComboBox()
        self.language_combo.addItems(['中文-普通话', '英语-美国', '英语-英国', '日语', '韩语'])
        control_layout.addWidget(QLabel('识别语言:'))
        control_layout.addWidget(self.language_combo)
        
        # 字体大小
        self.font_size = QSpinBox()
        self.font_size.setRange(10, 72)
        self.font_size.setValue(24)
        control_layout.addWidget(QLabel('字体大小:'))
        control_layout.addWidget(self.font_size)
        self.font_size.valueChanged.connect(self.change_font_size)
        
        layout.addLayout(control_layout)
        
        # 字幕显示区域
        self.subtitle_display = QTextEdit()
        self.subtitle_display.setReadOnly(True)
        self.subtitle_display.setAlignment(Qt.AlignCenter)
        self.subtitle_display.setFont(QFont('Arial', 24))
        self.subtitle_display.setStyleSheet("background-color: black; color: white;")
        layout.addWidget(self.subtitle_display, 1)
        
        # 按钮区域
        button_layout = QHBoxLayout()
        
        self.start_button = QPushButton('开始监听')
        self.start_button.clicked.connect(self.toggle_listening)
        button_layout.addWidget(self.start_button)
        
        self.clear_button = QPushButton('清除字幕')
        self.clear_button.clicked.connect(self.clear_text)
        button_layout.addWidget(self.clear_button)
        
        layout.addLayout(button_layout)
        
        # 状态栏
        self.status_bar = self.statusBar()
        self.show_status('准备就绪')
        
    def populate_audio_devices(self):
        """填充可用的音频设备"""
        self.device_combo.clear()
        count = self.pyaudio_instance.get_device_count()
        for i in range(count):
            info = self.pyaudio_instance.get_device_info_by_index(i)
            if info['maxInputChannels'] > 0:
                self.device_combo.addItem(info['name'], i)
        
        # 尝试找到默认的立体声混音设备
        for i in range(self.device_combo.count()):
            if "立体声混音" in self.device_combo.itemText(i) or "Stereo Mix" in self.device_combo.itemText(i):
                self.device_combo.setCurrentIndex(i)
                break
    
    def toggle_listening(self):
        """开始或停止监听"""
        if self.is_listening:
            self.stop_listening()
            self.start_button.setText('开始监听')
            self.show_status('已停止监听')
        else:
            if self.start_listening():
                self.start_button.setText('停止监听')
                self.show_status('正在监听...')
    
    def start_listening(self):
        """开始监听音频"""
        if self.is_listening:
            return False
        
        device_index = self.device_combo.currentData()
        if device_index is None:
            self.show_status('错误: 没有选择音频设备')
            return False
        
        try:
            self.audio_stream = self.pyaudio_instance.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=4096,
                stream_callback=self.audio_callback
            )
            
            self.is_listening = True
            threading.Thread(target=self.process_audio_queue, daemon=True).start()
            return True
        except Exception as e:
            self.show_status(f'错误: {str(e)}')
            return False
    
    def stop_listening(self):
        """停止监听音频"""
        if not self.is_listening:
            return
        
        self.is_listening = False
        if self.audio_stream:
            self.audio_stream.stop_stream()
            self.audio_stream.close()
            self.audio_stream = None
    
    def audio_callback(self, in_data, frame_count, time_info, status):
        """音频回调函数"""
        if self.is_listening:
            self.audio_queue.put(in_data)
        return (None, pyaudio.paContinue)
    
    def process_audio_queue(self):
        """处理音频队列中的数据进行识别"""
        while self.is_listening or not self.audio_queue.empty():
            try:
                audio_data = self.audio_queue.get(timeout=1)
                audio_frame = sr.AudioData(audio_data, 16000, 2)
                
                try:
                    # 根据选择的语言设置识别语言
                    language_map = {
                        '中文-普通话': 'zh-CN',
                        '英语-美国': 'en-US',
                        '英语-英国': 'en-GB',
                        '日语': 'ja-JP',
                        '韩语': 'ko-KR'
                    }
                    selected_lang = self.language_combo.currentText()
                    lang_code = language_map.get(selected_lang, 'zh-CN')
                    
                    text = self.recognizer.recognize_google(audio_frame, language=lang_code)
                    self.current_text = text
                    self.update_signal.emit(text)
                    self.show_status('识别成功')
                except sr.UnknownValueError:
                    self.show_status('无法识别语音')
                except sr.RequestError as e:
                    self.show_status(f'识别服务错误: {str(e)}')
                
            except queue.Empty:
                continue
    
    def update_display(self, text):
        """更新字幕显示"""
        self.subtitle_display.setPlainText(text)
    
    def clear_text(self):
        """清除字幕"""
        self.current_text = ""
        self.subtitle_display.clear()
    
    def change_font_size(self, size):
        """改变字体大小"""
        font = self.subtitle_display.font()
        font.setPointSize(size)
        self.subtitle_display.setFont(font)
    
    def show_status(self, message):
        """显示状态信息"""
        self.status_bar.showMessage(message)
    
    def closeEvent(self, event):
        """关闭窗口时停止监听"""
        self.stop_listening()
        self.pyaudio_instance.terminate()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # 使用Fusion风格使界面更现代
    
    # 设置暗色主题
    palette = app.palette()
    palette.setColor(QPalette.Window, QColor(53, 53, 53))
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ToolTipBase, Qt.white)
    palette.setColor(QPalette.ToolTipText, Qt.white)
    palette.setColor(QPalette.Text, Qt.white)
    palette.setColor(QPalette.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ButtonText, Qt.white)
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, Qt.black)
    app.setPalette(palette)
    
    transcriber = AudioTranscriber()
    transcriber.show()
    sys.exit(app.exec_())