import sys
import queue
import sounddevice as sd
import speech_recognition as sr
import numpy as np
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QWidget, 
                            QTextEdit, QPushButton, QLabel, QComboBox, QHBoxLayout,
                            QMessageBox, QGroupBox, QScrollArea)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QTextCursor, QColor, QPalette

class AudioDeviceMonitor(QThread):
    active_devices_updated = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self._running = True

    def run(self):
        while self._running:
            active_devices = []
            try:
                devices = sd.query_devices()
                status = sd.query_hostapis()
                
                for i, device in enumerate(devices):
                    # 检查设备是否正在活动状态
                    if device['hostapi'] < len(status):
                        api_status = status[device['hostapi']]
                        if api_status['defaultOutputDevice'] == i or api_status['defaultInputDevice'] == i:
                            active_devices.append(i)
                        elif device['max_output_channels'] > 0 and sd.check_output_settings(device=i):
                            active_devices.append(i)
                
                self.active_devices_updated.emit(active_devices)
            except:
                pass
            QThread.msleep(1000)

    def stop(self):
        self._running = False

class AudioCaptureThread(QThread):
    new_audio = pyqtSignal(object)
    error_occurred = pyqtSignal(str)
    status_update = pyqtSignal(str)

    def __init__(self, device_index):
        super().__init__()
        self.device_index = device_index
        self._running = False
        self.samplerate = None
        self.channels = None

    def run(self):
        self._running = True
        try:
            device_info = sd.query_devices(self.device_index)
            
            # 自动确定最佳参数
            self.samplerate = int(device_info.get('default_samplerate', 44100))
            self.channels = device_info.get('max_input_channels', 1)
            
            # 限制最大声道数不超过8
            self.channels = min(8, self.channels)
            
            self.status_update.emit(f"使用参数: {self.samplerate}Hz, {self.channels}声道")
            
            def callback(indata, frames, time, status):
                if not self._running:
                    raise sd.CallbackStop
                if status:
                    self.status_update.emit(f"音频状态: {status}")
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

class AdvancedAudioTranscriber(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("高级音频转字幕工具")
        self.setGeometry(100, 100, 1000, 800)
        
        # 初始化语音识别器
        self.recognizer = sr.Recognizer()
        self.audio_queue = queue.Queue()
        self.is_listening = False
        self.capture_thread = None
        self.monitor_thread = None
        self.active_devices = set()
        
        # 初始化UI
        self.init_ui()
        
        # 获取音频设备列表
        self.update_audio_devices()
        
        # 启动设备监控
        self.start_device_monitor()
        
    def init_ui(self):
        # 主窗口部件
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout()
        main_widget.setLayout(layout)
        
        # 标题
        title_label = QLabel("高级音频转字幕工具")
        title_label.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # 创建滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        content_layout = QVBoxLayout()
        content.setLayout(content_layout)
        layout.addWidget(scroll)
        
        # 设备信息组
        device_group = QGroupBox("音频设备信息")
        device_group.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        device_layout = QVBoxLayout()
        device_group.setLayout(device_layout)
        content_layout.addWidget(device_group)
        
        # 活动设备标签
        self.active_dev_label = QLabel("当前活动设备: 检测中...")
        self.active_dev_label.setFont(QFont("Microsoft YaHei", 10))
        device_layout.addWidget(self.active_dev_label)
        
        # 设备选择区域
        select_layout = QHBoxLayout()
        device_label = QLabel("选择捕获设备:")
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
        
        # 设备详情显示
        self.device_info_display = QTextEdit()
        self.device_info_display.setFont(QFont("Courier New", 9))
        self.device_info_display.setReadOnly(True)
        device_layout.addWidget(self.device_info_display)
        
        # 文本显示区域
        text_group = QGroupBox("实时字幕")
        text_group.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        text_layout = QVBoxLayout()
        text_group.setLayout(text_layout)
        content_layout.addWidget(text_group)
        
        self.text_display = QTextEdit()
        self.text_display.setFont(QFont("Microsoft YaHei", 12))
        self.text_display.setReadOnly(True)
        text_layout.addWidget(self.text_display)
        
        # 控制按钮区域
        control_layout = QHBoxLayout()
        self.start_btn = QPushButton("开始捕获")
        self.start_btn.setFont(QFont("Microsoft YaHei", 12))
        self.start_btn.clicked.connect(self.toggle_listening)
        self.start_btn.setEnabled(False)
        
        clear_btn = QPushButton("清空字幕")
        clear_btn.setFont(QFont("Microsoft YaHei", 12))
        clear_btn.clicked.connect(self.clear_text)
        
        help_btn = QPushButton("帮助")
        help_btn.setFont(QFont("Microsoft YaHei", 12))
        help_btn.clicked.connect(self.show_help)
        
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(clear_btn)
        control_layout.addWidget(help_btn)
        content_layout.addLayout(control_layout)
        
        # 状态栏
        self.status_label = QLabel("准备就绪")
        self.status_label.setFont(QFont("Microsoft YaHei", 10))
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)
        
        # 设置定时器处理音频队列
        self.timer = QTimer()
        self.timer.timeout.connect(self.process_audio_queue)
        self.timer.start(100)
    
    def start_device_monitor(self):
        self.monitor_thread = AudioDeviceMonitor()
        self.monitor_thread.active_devices_updated.connect(self.update_active_devices)
        self.monitor_thread.start()
    
    def update_active_devices(self, active_indices):
        self.active_devices = set(active_indices)
        active_names = []
        
        for i in active_indices:
            try:
                dev = sd.query_devices(i)
                active_names.append(dev['name'])
            except:
                pass
        
        if active_names:
            self.active_dev_label.setText("当前活动设备: " + ", ".join(active_names))
        else:
            self.active_dev_label.setText("当前没有检测到活动设备")
        
        # 更新设备列表高亮
        self.update_device_combo_highlight()
    
    def update_device_combo_highlight(self):
        palette = self.device_combo.palette()
        
        for i in range(self.device_combo.count()):
            device_index = self.device_combo.itemData(i)
            if device_index in self.active_devices:
                # 设置活动设备为绿色背景
                palette.setColor(QPalette.Highlight, QColor(144, 238, 144))
            else:
                # 非活动设备恢复默认
                palette.setColor(QPalette.Highlight, palette.color(QPalette.Active, QPalette.Highlight))
        
        self.device_combo.setPalette(palette)
    
    def update_audio_devices(self):
        self.device_combo.clear()
        self.start_btn.setEnabled(False)
        
        try:
            devices = sd.query_devices()
            hostapis = sd.query_hostapis()
            
            # 查找所有设备
            for i, device in enumerate(devices):
                try:
                    hostapi_name = hostapis[device['hostapi']]['name']
                    name = f"{device['name']} ({hostapi_name})"
                    
                    # 添加设备详细信息
                    details = []
                    if device['max_input_channels'] > 0:
                        details.append(f"输入:{device['max_input_channels']}ch")
                    if device['max_output_channels'] > 0:
                        details.append(f"输出:{device['max_output_channels']}ch")
                    if 'default_samplerate' in device:
                        details.append(f"{device['default_samplerate']}Hz")
                    
                    if details:
                        name += f" [{', '.join(details)}]"
                    
                    self.device_combo.addItem(name, userData=i)
                except:
                    continue
            
            if self.device_combo.count() > 0:
                self.status_label.setText(f"找到 {self.device_combo.count()} 个音频设备")
                self.start_btn.setEnabled(True)
                # 显示第一个设备的详细信息
                self.show_device_details(self.device_combo.itemData(0))
            else:
                self.status_label.setText("未找到可用的音频设备")
                self.show_help()
                
        except Exception as e:
            self.status_label.setText(f"获取设备列表失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"无法获取音频设备列表:\n{str(e)}")
    
    def show_device_details(self, device_index):
        try:
            device_info = sd.query_devices(device_index)
            details = []
            
            # 基本信息
            details.append(f"设备名称: {device_info.get('name', '未知')}")
            details.append(f"主机API: {device_info.get('hostapi', '未知')}")
            details.append(f"默认采样率: {device_info.get('default_samplerate', '未知')}Hz")
            details.append(f"最大输入声道数: {device_info.get('max_input_channels', '未知')}")
            details.append(f"最大输出声道数: {device_info.get('max_output_channels', '未知')}")
            
            # 高级信息
            details.append("\n高级信息:")
            for key, value in device_info.items():
                if key not in ['name', 'hostapi', 'default_samplerate', 'max_input_channels', 'max_output_channels']:
                    details.append(f"{key}: {value}")
            
            self.device_info_display.setPlainText("\n".join(details))
        except Exception as e:
            self.device_info_display.setPlainText(f"无法获取设备详细信息: {str(e)}")
    
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
                except Exception as e:
                    self.status_label.setText(f"启动失败: {str(e)}")
                    QMessageBox.warning(self, "错误", f"无法开始捕获音频:\n{str(e)}")
            else:
                self.status_label.setText("请先选择音频设备")
    
    def start_capture(self):
        device_index = self.device_combo.currentData()
        
        # 显示设备详情
        self.show_device_details(device_index)
        
        # 创建并启动捕获线程
        self.capture_thread = AudioCaptureThread(device_index)
        self.capture_thread.new_audio.connect(self.handle_new_audio)
        self.capture_thread.error_occurred.connect(self.handle_capture_error)
        self.capture_thread.status_update.connect(self.status_label.setText)
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
        self.start_btn.setText("开始捕获")
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
    
    def show_help(self):
        help_text = """
        <h3>高级音频转字幕工具使用帮助</h3>
        
        <p><b>功能说明:</b></p>
        <ul>
            <li>实时监控系统所有音频设备</li>
            <li>自动检测当前正在播放声音的设备</li>
            <li>支持多声道音频捕获(最高7.1声道)</li>
            <li>自动适配设备的最佳采样率和声道配置</li>
            <li>显示详细的设备技术参数</li>
        </ul>
        
        <p><b>使用步骤:</b></p>
        <ol>
            <li>查看"当前活动设备"确定哪个设备正在播放声音</li>
            <li>从下拉列表中选择要捕获的设备</li>
            <li>点击"开始捕获"按钮</li>
            <li>播放您想要转换的音频内容</li>
        </ol>
        
        <p><b>常见问题:</b></p>
        <ul>
            <li><b>没有显示设备?</b><br>
                请检查音频驱动是否安装正确，专业声卡可能需要特定驱动</li>
            <li><b>无法捕获多声道音频?</b><br>
                确保选择了正确的设备，某些设备可能需要管理员权限</li>
            <li><b>识别结果不准确?</b><br>
                尝试选择不同的设备或检查网络连接(使用Google语音识别API)</li>
        </ul>
        """
        QMessageBox.information(self, "帮助信息", help_text)
    
    def closeEvent(self, event):
        if self.is_listening:
            self.stop_capture()
        if self.monitor_thread is not None:
            self.monitor_thread.stop()
            self.monitor_thread.quit()
            self.monitor_thread.wait()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AdvancedAudioTranscriber()
    window.show()
    sys.exit(app.exec_())