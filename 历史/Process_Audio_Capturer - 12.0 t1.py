import sys
import threading
import queue
import json
import os
import pyaudio
from vosk import Model, KaldiRecognizer
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QWidget, 
                            QLabel, QPushButton, QTextEdit, QComboBox, 
                            QHBoxLayout, QSpinBox, QSizePolicy, QCheckBox,
                            QLineEdit, QGroupBox)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QPalette

class AudioTranscriber(QMainWindow):
    update_signal = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.audio_queue = queue.Queue()
        self.is_listening = False
        self.audio_stream = None
        self.pyaudio_instance = pyaudio.PyAudio()
        self.current_text = ""
        self.recognizer = None
        self.model = None
        self.init_ui()
        self.update_signal.connect(self.update_display)
        self.load_offline_model()
        
    def init_ui(self):
        """初始化用户界面"""
        self.setWindowTitle('离线音频转字幕工具')
        self.setGeometry(100, 100, 800, 500)
        
        # 主窗口部件
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        
        # 标题
        title_label = QLabel('离线音频转字幕')
        title_label.setFont(QFont('Arial', 18, QFont.Bold))
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # 模型设置组
        model_group = QGroupBox("模型设置")
        model_layout = QVBoxLayout()
        
        # 模型选择
        self.model_combo = QComboBox()
        self.model_combo.addItems(['vosk-model-cn-0.22', 'vosk-model-cn-kaldi-multicn-0.15', 'vosk-model-small-cn-0.22'])
        model_layout.addWidget(QLabel('选择离线模型:'))
        model_layout.addWidget(self.model_combo)
        
        # 在线识别选项
        self.online_check = QCheckBox('启用在线识别(需要代理)')
        model_layout.addWidget(self.online_check)
        
        # 代理设置
        proxy_layout = QHBoxLayout()
        proxy_layout.addWidget(QLabel('代理地址:'))
        self.proxy_edit = QLineEdit('http://127.0.0.1:20808')
        proxy_layout.addWidget(self.proxy_edit)
        model_layout.addLayout(proxy_layout)
        
        model_group.setLayout(model_layout)
        layout.addWidget(model_group)
        
        # 设备设置组
        device_group = QGroupBox("音频设置")
        device_layout = QHBoxLayout()
        
        # 设备选择
        self.device_combo = QComboBox()
        self.populate_audio_devices()
        device_layout.addWidget(QLabel('音频设备:'))
        device_layout.addWidget(self.device_combo)
        
        # 采样率
        self.sample_rate = QSpinBox()
        self.sample_rate.setRange(8000, 48000)
        self.sample_rate.setValue(16000)
        device_layout.addWidget(QLabel('采样率:'))
        device_layout.addWidget(self.sample_rate)
        
        device_group.setLayout(device_layout)
        layout.addWidget(device_group)
        
        # 显示设置组
        display_group = QGroupBox("显示设置")
        display_layout = QHBoxLayout()
        
        # 字体大小
        self.font_size = QSpinBox()
        self.font_size.setRange(10, 72)
        self.font_size.setValue(24)
        display_layout.addWidget(QLabel('字体大小:'))
        display_layout.addWidget(self.font_size)
        self.font_size.valueChanged.connect(self.change_font_size)
        
        # 文本颜色
        self.text_color = QComboBox()
        self.text_color.addItems(['白色', '黄色', '绿色', '红色', '蓝色'])
        display_layout.addWidget(QLabel('文本颜色:'))
        display_layout.addWidget(self.text_color)
        self.text_color.currentIndexChanged.connect(self.change_text_color)
        
        display_group.setLayout(display_layout)
        layout.addWidget(display_group)
        
        # 字幕显示区域
        self.subtitle_display = QTextEdit()
        self.subtitle_display.setReadOnly(True)
        self.subtitle_display.setAlignment(Qt.AlignCenter)
        self.subtitle_display.setFont(QFont('Microsoft YaHei', 24))
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
            # 只显示输出设备(扬声器)
            if info['maxOutputChannels'] > 0:
                self.device_combo.addItem(f"{info['name']} (ID: {i})", i)
        
        # 尝试找到默认的立体声混音设备
        for i in range(self.device_combo.count()):
            if "立体声混音" in self.device_combo.itemText(i) or "Stereo Mix" in self.device_combo.itemText(i):
                self.device_combo.setCurrentIndex(i)
                break
    
    def load_offline_model(self):
        """加载离线模型"""
        model_dir = self.model_combo.currentText()
        if not os.path.exists(model_dir):
            self.show_status(f'错误: 模型目录 {model_dir} 不存在')
            return False
        
        try:
            self.model = Model(model_dir)
            sample_rate = self.sample_rate.value()
            self.recognizer = KaldiRecognizer(self.model, sample_rate)
            self.recognizer.SetWords(True)
            self.show_status(f'已加载模型: {model_dir}')
            return True
        except Exception as e:
            self.show_status(f'加载模型错误: {str(e)}')
            return False
    
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
        
        # 重新加载模型（如果更换了模型）
        if not self.load_offline_model():
            return False
        
        try:
            sample_rate = self.sample_rate.value()
            self.audio_stream = self.pyaudio_instance.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=sample_rate,
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
                
                if self.recognizer.AcceptWaveform(audio_data):
                    result = json.loads(self.recognizer.Result())
                    text = result.get('text', '')
                    if text:
                        self.current_text = text
                        self.update_signal.emit(text)
                        self.show_status('识别成功')
                
                # 部分结果（实时性更好）
                partial_result = json.loads(self.recognizer.PartialResult())
                partial_text = partial_result.get('partial', '')
                if partial_text:
                    self.update_signal.emit(partial_text)
                
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
    
    def change_text_color(self):
        """改变文本颜色"""
        color_map = {
            '白色': 'white',
            '黄色': 'yellow',
            '绿色': 'lime',
            '红色': 'red',
            '蓝色': 'cyan'
        }
        color = color_map.get(self.text_color.currentText(), 'white')
        self.subtitle_display.setStyleSheet(f"background-color: black; color: {color};")
    
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