import sys
import time
import queue
import json
import sounddevice as sd
import speech_recognition as sr
import numpy as np
import urllib.request
from vosk import Model, KaldiRecognizer
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QWidget, 
                            QTextEdit, QPushButton, QLabel, QComboBox, QHBoxLayout,
                            QMessageBox, QGroupBox, QScrollArea, QCheckBox, QLineEdit)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QMutex
from PyQt5.QtGui import QFont, QTextCursor, QColor, QPalette

class AudioCaptureThread(QThread):
    new_audio = pyqtSignal(object)
    error_occurred = pyqtSignal(str)
    status_update = pyqtSignal(str)
    performance_warning = pyqtSignal(str)

    def __init__(self, device_index):
        super().__init__()
        self.device_index = device_index
        self._running = False
        self.samplerate = 16000
        self.channels = 1
        self.audio_buffer = queue.Queue(maxsize=20)
        self.mutex = QMutex()

    def run(self):
        self._running = True
        try:
            device_info = sd.query_devices(self.device_index)
            self.samplerate = min(44100, int(device_info.get('default_samplerate', 44100)))
            self.channels = min(2, device_info.get('max_input_channels', 1))
            
            self.status_update.emit(f"使用参数: {self.samplerate}Hz, {self.channels}声道")
            
            def callback(indata, frames, time, status):
                if not self._running:
                    raise sd.CallbackStop
                try:
                    audio_data = (indata[:, 0] * 32767).astype(np.int16).tobytes() if self.channels > 1 else \
                                 (indata * 32767).astype(np.int16).tobytes()
                    if self.audio_buffer.qsize() < 15:
                        audio = sr.AudioData(audio_data, self.samplerate, 1)
                        self.audio_buffer.put_nowait(audio)
                except:
                    pass

            with sd.InputStream(
                device=self.device_index,
                channels=self.channels,
                samplerate=self.samplerate,
                callback=callback,
                blocksize=1024,
                latency='low'
            ):
                last_warning_time = 0
                while self._running:
                    try:
                        sd.sleep(50)
                        while not self.audio_buffer.empty():
                            audio = self.audio_buffer.get_nowait()
                            self.new_audio.emit(audio)
                        if self.audio_buffer.qsize() > 10:
                            current_time = time.time()
                            if current_time - last_warning_time > 5:
                                self.performance_warning.emit(
                                    f"高负载警告: 音频缓冲区积压({self.audio_buffer.qsize()})"
                                )
                                last_warning_time = current_time
                    except:
                        pass
        except Exception as e:
            self.error_occurred.emit(str(e))
        finally:
            self._running = False

    def stop(self):
        self._running = False
        self.wait()

class EnhancedAudioTranscriber(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("增强版音频转字幕工具")
        self.setGeometry(100, 100, 1000, 800)
        
        # 初始化设置
        self.max_text_length = 10000
        self.last_process_time = 0
        self.process_interval = 0.1
        self.recognizer = sr.Recognizer()
        self.audio_queue = queue.Queue(maxsize=10)
        self.is_listening = False
        self.capture_thread = None
        self.vosk_model = None
        self.vosk_recognizer = None
        
        # 代理设置
        self.proxy_config = {
            'http': 'socks5://127.0.0.1:20808',
            'https': 'socks5://127.0.0.1:20808'
        }
        
        # 初始化UI
        self.init_ui()
        self.update_audio_devices()
    
    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout()
        main_widget.setLayout(layout)
        
        # 标题
        title_label = QLabel("增强版音频转字幕工具")
        title_label.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # 识别模式选择
        mode_group = QGroupBox("识别模式设置")
        mode_group.setFont(QFont("Microsoft YaHei", 10))
        mode_layout = QVBoxLayout()
        mode_group.setLayout(mode_layout)
        
        self.online_radio = QCheckBox("在线识别 (Google)")
        self.online_radio.setFont(QFont("Microsoft YaHei", 10))
        self.online_radio.setChecked(True)
        self.online_radio.toggled.connect(self.update_recognition_mode)
        
        self.offline_radio = QCheckBox("离线识别 (Vosk)")
        self.offline_radio.setFont(QFont("Microsoft YaHei", 10))
        
        mode_layout.addWidget(self.online_radio)
        mode_layout.addWidget(self.offline_radio)
        layout.addWidget(mode_group)
        
        # 代理设置
        proxy_group = QGroupBox("代理设置 (仅在线模式)")
        proxy_group.setFont(QFont("Microsoft YaHei", 10))
        proxy_layout = QVBoxLayout()
        proxy_group.setLayout(proxy_layout)
        
        self.proxy_edit = QLineEdit()
        self.proxy_edit.setFont(QFont("Microsoft YaHei", 10))
        self.proxy_edit.setText("socks5://127.0.0.1:20808")
        self.proxy_edit.setPlaceholderText("输入代理地址，如: http://127.0.0.1:20808")
        
        proxy_test_btn = QPushButton("测试代理连接")
        proxy_test_btn.setFont(QFont("Microsoft YaHei", 10))
        proxy_test_btn.clicked.connect(self.test_proxy_connection)
        
        proxy_layout.addWidget(QLabel("代理地址:"))
        proxy_layout.addWidget(self.proxy_edit)
        proxy_layout.addWidget(proxy_test_btn)
        layout.addWidget(proxy_group)
        
        # 设备设置
        device_group = QGroupBox("音频设备设置")
        device_group.setFont(QFont("Microsoft YaHei", 10))
        device_layout = QVBoxLayout()
        device_group.setLayout(device_layout)
        
        select_layout = QHBoxLayout()
        device_label = QLabel("选择音频设备:")
        device_label.setFont(QFont("Microsoft YaHei", 10))
        self.device_combo = QComboBox()
        self.device_combo.setFont(QFont("Microsoft YaHei", 10))
        refresh_btn = QPushButton("刷新设备")
        refresh_btn.setFont(QFont("Microsoft YaHei", 10))
        refresh_btn.clicked.connect(self.update_audio_devices)
        
        select_layout.addWidget(device_label)
        select_layout.addWidget(self.device_combo)
        select_layout.addWidget(refresh_btn)
        device_layout.addLayout(select_layout)
        
        perf_layout = QHBoxLayout()
        self.low_latency_check = QCheckBox("低延迟模式")
        self.low_latency_check.setFont(QFont("Microsoft YaHei", 10))
        self.low_latency_check.setChecked(True)
        
        self.mono_check = QCheckBox("强制单声道")
        self.mono_check.setFont(QFont("Microsoft YaHei", 10))
        self.mono_check.setChecked(True)
        
        perf_layout.addWidget(self.low_latency_check)
        perf_layout.addWidget(self.mono_check)
        device_layout.addLayout(perf_layout)
        layout.addWidget(device_group)
        
        # 文本显示
        text_group = QGroupBox("实时字幕")
        text_group.setFont(QFont("Microsoft YaHei", 10))
        text_layout = QVBoxLayout()
        text_group.setLayout(text_layout)
        
        self.text_display = QTextEdit()
        self.text_display.setFont(QFont("Microsoft YaHei", 12))
        self.text_display.setReadOnly(True)
        text_layout.addWidget(self.text_display)
        layout.addWidget(text_group)
        
        # 控制按钮
        control_layout = QHBoxLayout()
        self.start_btn = QPushButton("开始捕获")
        self.start_btn.setFont(QFont("Microsoft YaHei", 12))
        self.start_btn.clicked.connect(self.toggle_listening)
        self.start_btn.setEnabled(False)
        
        clear_btn = QPushButton("清空字幕")
        clear_btn.setFont(QFont("Microsoft YaHei", 12))
        clear_btn.clicked.connect(self.clear_text)
        
        pause_btn = QPushButton("暂停")
        pause_btn.setFont(QFont("Microsoft YaHei", 12))
        pause_btn.clicked.connect(self.toggle_pause)
        
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(clear_btn)
        control_layout.addWidget(pause_btn)
        layout.addLayout(control_layout)
        
        # 状态栏
        self.status_label = QLabel("准备就绪")
        self.status_label.setFont(QFont("Microsoft YaHei", 10))
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)
        
        # 定时器
        self.timer = QTimer()
        self.timer.timeout.connect(self.process_audio_queue)
        self.timer.start(100)
        
        # 初始化离线模型
        self.init_offline_model()
    
    def init_offline_model(self):
        try:
            self.status_label.setText("正在加载离线模型...")
            QApplication.processEvents()  # 更新UI
            
            # 这里需要替换为实际的Vosk模型路径
            # 可以从 https://alphacephei.com/vosk/models 下载中文模型
            model_path = "vosk-model-small-zh-cn-0.22"  # 修改为你的模型路径
            self.vosk_model = Model(model_path)
            self.status_label.setText("离线模型加载完成")
        except Exception as e:
            self.status_label.setText(f"离线模型加载失败: {str(e)}")
            self.offline_radio.setEnabled(False)
    
    def update_recognition_mode(self, checked):
        if checked:
            self.offline_radio.setChecked(False)
        else:
            self.offline_radio.setChecked(True)
    
    def test_proxy_connection(self):
        proxy_url = self.proxy_edit.text().strip()
        if not proxy_url:
            QMessageBox.warning(self, "警告", "请输入代理地址")
            return
        
        try:
            # 设置代理
            proxy_handler = urllib.request.ProxyHandler({
                'http': proxy_url,
                'https': proxy_url
            })
            opener = urllib.request.build_opener(proxy_handler)
            urllib.request.install_opener(opener)
            
            # 测试连接
            response = urllib.request.urlopen('https://www.google.com', timeout=5)
            if response.status == 200:
                QMessageBox.information(self, "成功", "代理连接测试成功")
                self.proxy_config = {
                    'http': proxy_url,
                    'https': proxy_url
                }
            else:
                QMessageBox.warning(self, "警告", "代理连接测试失败")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"代理连接测试失败:\n{str(e)}")
    
    def toggle_pause(self):
        if hasattr(self, 'is_paused'):
            self.is_paused = not self.is_paused
            self.status_label.setText("已恢复" if not self.is_paused else "已暂停")
        else:
            self.is_paused = True
            self.status_label.setText("已暂停")
    
    def update_audio_devices(self):
        self.device_combo.clear()
        self.start_btn.setEnabled(False)
        
        try:
            devices = sd.query_devices()
            for i, device in enumerate(devices):
                if device['max_input_channels'] > 0:
                    name = f"{device['name']} (输入:{device['max_input_channels']}ch"
                    if 'default_samplerate' in device:
                        name += f", {device['default_samplerate']}Hz"
                    name += ")"
                    self.device_combo.addItem(name, userData=i)
            
            if self.device_combo.count() > 0:
                self.status_label.setText(f"找到 {self.device_combo.count()} 个音频设备")
                self.start_btn.setEnabled(True)
            else:
                self.status_label.setText("未找到可用的音频输入设备")
                QMessageBox.information(self, "提示", 
                    "没有找到可用的音频输入设备。\n"
                    "如果您想捕获系统声音，请安装虚拟音频设备:\n"
                    "Windows: VB-Cable\n"
                    "macOS: BlackHole\n"
                    "Linux: PulseAudio loopback")
        except Exception as e:
            self.status_label.setText(f"获取设备列表失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"无法获取音频设备列表:\n{str(e)}")
    
    def toggle_listening(self):
        if self.is_listening:
            self.stop_capture()
            self.is_listening = False
            self.start_btn.setText("开始捕获")
            self.status_label.setText("已停止")
        else:
            selected_index = self.device_combo.currentIndex()
            if selected_index >= 0:
                try:
                    self.start_capture()
                    self.is_listening = True
                    self.start_btn.setText("停止捕获")
                    self.status_label.setText("正在初始化...")
                    self.is_paused = False
                except Exception as e:
                    self.status_label.setText(f"启动失败: {str(e)}")
                    QMessageBox.warning(self, "错误", f"无法开始捕获音频:\n{str(e)}")
            else:
                self.status_label.setText("请先选择音频设备")
    
    def start_capture(self):
        device_index = self.device_combo.currentData()
        
        # 初始化Vosk识别器（如果使用离线模式）
        if self.offline_radio.isChecked():
            device_info = sd.query_devices(device_index)
            samplerate = int(device_info.get('default_samplerate', 16000))
            self.vosk_recognizer = KaldiRecognizer(self.vosk_model, samplerate)
        
        # 创建并启动捕获线程
        self.capture_thread = AudioCaptureThread(device_index)
        self.capture_thread.new_audio.connect(self.handle_new_audio)
        self.capture_thread.error_occurred.connect(self.handle_capture_error)
        self.capture_thread.status_update.connect(self.status_label.setText)
        self.capture_thread.performance_warning.connect(self.show_warning)
        self.capture_thread.start()
    
    def show_warning(self, message):
        QMessageBox.warning(self, "性能警告", message)
    
    def stop_capture(self):
        if self.capture_thread is not None:
            self.capture_thread.stop()
            self.capture_thread = None
        self.vosk_recognizer = None
    
    def handle_new_audio(self, audio):
        try:
            if self.audio_queue.qsize() < 5:
                self.audio_queue.put_nowait(audio)
        except:
            pass
    
    def handle_capture_error(self, error_msg):
        self.status_label.setText(f"捕获错误: {error_msg}")
        self.stop_capture()
        self.is_listening = False
        self.start_btn.setText("开始捕获")
        QMessageBox.warning(self, "错误", f"音频捕获发生错误:\n{error_msg}")
    
    def process_audio_queue(self):
        if hasattr(self, 'is_paused') and self.is_paused:
            return
            
        current_time = time.time()
        if current_time - self.last_process_time < self.process_interval:
            return
            
        self.last_process_time = current_time
        
        try:
            audio = self.audio_queue.get_nowait()
            
            # 离线识别模式
            if self.offline_radio.isChecked() and self.vosk_recognizer:
                if self.vosk_recognizer.AcceptWaveform(audio.get_raw_data()):
                    result = json.loads(self.vosk_recognizer.Result())
                    text = result.get('text', '')
                    if text:
                        self.append_text(text)
                return
            
            # 在线识别模式
            try:
                # 设置代理
                if self.proxy_config['http']:
                    self.recognizer.proxy = self.proxy_config
                
                text = self.recognizer.recognize_google(
                    audio, 
                    language="zh-CN",
                    show_all=False
                )
                self.append_text(text)
            except sr.UnknownValueError:
                pass
            except sr.RequestError as e:
                self.append_text(f"(在线识别错误: {str(e)})")
            except Exception as e:
                self.append_text(f"(错误: {str(e)})")
        except queue.Empty:
            pass
    
    def append_text(self, text):
        if len(self.text_display.toPlainText()) > self.max_text_length:
            self.text_display.clear()
            
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
    # 配置音频系统参数
    sd._terminate()
    sd._initialize()
    
    app = QApplication(sys.argv)
    window = EnhancedAudioTranscriber()
    window.show()
    sys.exit(app.exec_())