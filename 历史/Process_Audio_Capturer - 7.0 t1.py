import sys
import queue
import sounddevice as sd
import speech_recognition as sr
import numpy as np
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QWidget, 
                            QTextEdit, QPushButton, QLabel, QComboBox, QHBoxLayout,
                            QMessageBox, QCheckBox)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QTextCursor

class AudioCaptureThread(QThread):
    new_audio = pyqtSignal(object)
    error_occurred = pyqtSignal(str)

    def __init__(self, device_index, samplerate, channels):
        super().__init__()
        self.device_index = device_index
        self.samplerate = samplerate
        self.channels = channels
        self._running = False

    def run(self):
        self._running = True
        try:
            def callback(indata, frames, time, status):
                if not self._running:
                    raise sd.CallbackStop
                audio_data = (indata * 32767).astype(np.int16).tobytes()
                audio = sr.AudioData(audio_data, self.samplerate, self.channels)
                self.new_audio.emit(audio)

            with sd.InputStream(
                device=self.device_index,
                channels=self.channels,
                samplerate=self.samplerate,
                callback=callback,
                blocksize=4096
            ):
                while self._running:
                    sd.sleep(100)
        except Exception as e:
            self.error_occurred.emit(str(e))

    def stop(self):
        self._running = False

class SystemAudioTranscriber(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("系统播放声音实时转字幕")
        self.setGeometry(100, 100, 800, 600)
        
        # 初始化语音识别器
        self.recognizer = sr.Recognizer()
        self.audio_queue = queue.Queue()
        self.is_listening = False
        self.capture_thread = None
        
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
        title_label = QLabel("系统播放声音实时转字幕")
        title_label.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # 设备选择区域
        device_layout = QHBoxLayout()
        device_label = QLabel("选择输出设备:")
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
        
        # 高级选项
        self.advanced_check = QCheckBox("显示高级选项")
        self.advanced_check.setFont(QFont("Microsoft YaHei", 10))
        self.advanced_check.toggled.connect(self.toggle_advanced)
        layout.addWidget(self.advanced_check)
        
        # 高级选项面板 (初始隐藏)
        self.advanced_panel = QWidget()
        advanced_layout = QVBoxLayout()
        self.advanced_panel.setLayout(advanced_layout)
        self.advanced_panel.hide()
        
        # 采样率选择
        samplerate_layout = QHBoxLayout()
        samplerate_label = QLabel("采样率:")
        samplerate_label.setFont(QFont("Microsoft YaHei", 10))
        self.samplerate_combo = QComboBox()
        self.samplerate_combo.addItems(["44100", "48000", "16000", "22050"])
        self.samplerate_combo.setCurrentIndex(0)
        samplerate_layout.addWidget(samplerate_label)
        samplerate_layout.addWidget(self.samplerate_combo)
        advanced_layout.addLayout(samplerate_layout)
        
        # 通道数选择
        channels_layout = QHBoxLayout()
        channels_label = QLabel("通道数:")
        channels_label.setFont(QFont("Microsoft YaHei", 10))
        self.channels_combo = QComboBox()
        self.channels_combo.addItems(["1 (单声道)", "2 (立体声)"])
        self.channels_combo.setCurrentIndex(1)
        channels_layout.addWidget(channels_label)
        channels_layout.addWidget(self.channels_combo)
        advanced_layout.addLayout(channels_layout)
        
        layout.addWidget(self.advanced_panel)
        
        # 帮助按钮
        help_btn = QPushButton("如何使用?")
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
        self.start_btn = QPushButton("开始转字幕")
        self.start_btn.setFont(QFont("Microsoft YaHei", 12))
        self.start_btn.clicked.connect(self.toggle_listening)
        self.start_btn.setEnabled(False)
        
        clear_btn = QPushButton("清空字幕")
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
    
    def toggle_advanced(self, checked):
        self.advanced_panel.setVisible(checked)
        self.adjustSize()
    
    def show_help(self):
        help_text = """
        <h3>系统播放声音实时转字幕使用指南</h3>
        <p><b>基本使用方法:</b></p>
        <ol>
            <li>选择您正在播放声音的输出设备</li>
            <li>点击"开始转字幕"按钮</li>
            <li>播放视频/音乐等有声音的内容</li>
            <li>实时字幕将显示在窗口中</li>
        </ol>
        
        <p><b>常见问题解决:</b></p>
        <ul>
            <li><b>没有可用的设备?</b> - 请安装虚拟音频设备:
                <br>Windows: VB-Cable 或 Voicemeeter
                <br>macOS: BlackHole
                <br>Linux: PulseAudio module-loopback</li>
            <li><b>识别不准确?</b> - 尝试在高级选项中降低采样率(如16000)</li>
            <li><b>有延迟?</b> - 尝试在高级选项中选择单声道</li>
        </ul>
        """
        QMessageBox.information(self, "帮助信息", help_text)
    
    def update_audio_devices(self):
        self.device_combo.clear()
        self.start_btn.setEnabled(False)
        
        try:
            devices = sd.query_devices()
            hostapis = sd.query_hostapis()
            
            # 查找所有输出设备
            output_devices = []
            for i, device in enumerate(devices):
                if device['max_output_channels'] > 0:
                    hostapi_name = hostapis[device['hostapi']]['name']
                    # 优先显示可能支持循环回放的设备
                    if ('Loopback' in device['name'] or 
                        'Virtual' in device['name'] or 
                        'Cable' in device['name'] or
                        '混音' in device['name']):
                        output_devices.insert(0, (i, f"★ {device['name']} ({hostapi_name})"))
                    else:
                        output_devices.append((i, f"{device['name']} ({hostapi_name})"))
            
            for i, name in output_devices:
                self.device_combo.addItem(name, userData=i)
            
            if self.device_combo.count() > 0:
                self.status_label.setText(f"找到 {self.device_combo.count()} 个输出设备")
                self.start_btn.setEnabled(True)
            else:
                self.status_label.setText("未找到输出设备")
                self.show_help()
                
        except Exception as e:
            self.status_label.setText(f"获取设备列表失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"无法获取音频设备列表:\n{str(e)}")
    
    def toggle_listening(self):
        if self.is_listening:
            self.stop_capture()
            self.is_listening = False
            self.start_btn.setText("开始转字幕")
            self.status_label.setText("已停止")
        else:
            selected_index = self.device_combo.currentIndex()
            if selected_index >= 0:
                try:
                    self.start_capture()
                    self.is_listening = True
                    self.start_btn.setText("停止转字幕")
                    self.status_label.setText("正在转换系统播放声音...")
                except Exception as e:
                    self.status_label.setText(f"启动失败: {str(e)}")
                    QMessageBox.warning(self, "错误", f"无法开始捕获音频:\n{str(e)}")
            else:
                self.status_label.setText("请先选择输出设备")
    
    def start_capture(self):
        device_index = self.device_combo.currentData()
        
        # 获取参数
        samplerate = int(self.samplerate_combo.currentText())
        channels = 1 if self.channels_combo.currentIndex() == 0 else 2
        
        # 创建并启动捕获线程
        self.capture_thread = AudioCaptureThread(device_index, samplerate, channels)
        self.capture_thread.new_audio.connect(self.handle_new_audio)
        self.capture_thread.error_occurred.connect(self.handle_capture_error)
        self.capture_thread.start()
    
    def stop_capture(self):
        if self.capture_thread is not None:
            self.capture_thread.stop()
            self.capture_thread.quit()
            self.capture_thread.wait()
            self.capture_thread = None
    
    def handle_new_audio(self, audio):
        self.audio_queue.put(audio)
    
    def handle_capture_error(self, error_msg):
        self.status_label.setText(f"捕获错误: {error_msg}")
        self.stop_capture()
        self.is_listening = False
        self.start_btn.setText("开始转字幕")
        QMessageBox.warning(self, "错误", f"音频捕获发生错误:\n{error_msg}")
    
    def process_audio_queue(self):
        while not self.audio_queue.empty():
            audio = self.audio_queue.get()
            try:
                text = self.recognizer.recognize_google(audio, language="zh-CN")
                self.append_text(text)
            except sr.UnknownValueError:
                pass  # 静默忽略无法识别的音频
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
            self.stop_capture()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SystemAudioTranscriber()
    window.show()
    sys.exit(app.exec_())