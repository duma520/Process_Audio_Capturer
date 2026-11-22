import os
import sys
import json
import queue
import psutil
import pyaudio
import sounddevice as sd
import win32gui
import win32process
from vosk import Model, KaldiRecognizer
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QWidget,
    QLabel, QTextEdit, QPushButton, QComboBox,
    QCheckBox, QHBoxLayout, QMessageBox
)
from PyQt5.QtCore import Qt, QTimer

class ProcessAudioCapturer:
    def __init__(self, model_path=None):
        self.audio = pyaudio.PyAudio()
        self.stream = None
        self.model_path = model_path
        self.recognizer = None
        self.sample_rate = 44100
        self.chunk = 1024
        self.current_process = None
        self.text_queue = queue.Queue()
        
        if model_path and os.path.exists(model_path):
            self.model = Model(model_path)
        else:
            self.model = None

    def list_audio_devices(self):
        """列出所有音频输入设备"""
        devices = []
        for i in range(self.audio.get_device_count()):
            dev = self.audio.get_device_info_by_index(i)
            if dev['maxInputChannels'] > 0:
                devices.append({
                    'index': i,
                    'name': dev['name'],
                    'channels': dev['maxInputChannels']
                })
        return devices

    def find_vb_cable_device(self):
        """查找VB-Cable虚拟设备"""
        for i in range(self.audio.get_device_count()):
            dev = self.audio.get_device_info_by_index(i)
            if 'cable' in dev['name'].lower() and dev['maxInputChannels'] > 0:
                return {
                    'index': i,
                    'name': dev['name'],
                    'channels': min(2, dev['maxInputChannels']),
                    'rate': 44100
                }
        return None

    def get_foreground_process(self):
        """获取当前前台窗口对应的进程"""
        window = win32gui.GetForegroundWindow()
        pid = win32process.GetWindowThreadProcessId(window)[1]
        try:
            return psutil.Process(pid)
        except psutil.NoSuchProcess:
            return None

    def route_process_audio(self, process_name):
        """将指定进程的音频路由到VB-Cable（需要手动配置）"""
        # 这里需要用户手动在系统声音设置中配置
        # 可以使用AutoHotkey脚本自动化此过程
        print(f"请手动将'{process_name}'的音频输出设置为'CABLE Input (VB-Audio Virtual Cable)'")

    def start_capture(self, callback):
        """开始捕获音频"""
        device = self.find_vb_cable_device()
        if not device:
            raise Exception("未找到VB-Cable设备，请先安装VB-Cable")
        
        if self.model:
            self.recognizer = KaldiRecognizer(self.model, device['rate'])
            self.recognizer.SetWords(True)
        
        self.stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=device['channels'],
            rate=device['rate'],
            input=True,
            input_device_index=device['index'],
            frames_per_buffer=self.chunk,
            stream_callback=callback,
            start=False
        )
        self.stream.start_stream()

    def stop_capture(self):
        """停止捕获"""
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        self.stream = None

    def process_audio(self, data):
        """处理音频数据"""
        if self.recognizer and self.recognizer.AcceptWaveform(data):
            result = json.loads(self.recognizer.Result())
            text = result.get('text', '')
            if text:
                self.text_queue.put(text)

class SubtitleApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.capturer = None
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle('进程音频实时字幕')
        self.setGeometry(100, 100, 800, 600)
        
        main_widget = QWidget()
        layout = QVBoxLayout()
        
        # 标题
        title_label = QLabel('进程音频实时字幕转换')
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet('font-size: 20px; font-weight: bold;')
        layout.addWidget(title_label)
        
        # 进程选择
        self.process_combo = QComboBox()
        self.refresh_processes()
        layout.addWidget(QLabel("选择目标进程:"))
        layout.addWidget(self.process_combo)
        
        # 设备信息
        self.device_label = QLabel("检测到的VB-Cable设备: 无")
        layout.addWidget(self.device_label)
        
        # 字幕显示
        self.subtitle_display = QTextEdit()
        self.subtitle_display.setReadOnly(True)
        self.subtitle_display.setStyleSheet('font-size: 16px;')
        layout.addWidget(self.subtitle_display, 1)
        
        # 控制按钮
        btn_layout = QHBoxLayout()
        
        self.start_btn = QPushButton('开始捕获')
        self.start_btn.clicked.connect(self.start_capture)
        btn_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton('停止捕获')
        self.stop_btn.clicked.connect(self.stop_capture)
        self.stop_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_btn)
        
        self.refresh_btn = QPushButton('刷新进程列表')
        self.refresh_btn.clicked.connect(self.refresh_processes)
        btn_layout.addWidget(self.refresh_btn)
        
        layout.addLayout(btn_layout)
        
        # 状态栏
        self.status_label = QLabel("就绪")
        layout.addWidget(self.status_label)
        
        main_widget.setLayout(layout)
        self.setCentralWidget(main_widget)
        
        # 定时器
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_ui)
        self.timer.start(100)
        
        # 初始化音频设备检测
        self.check_audio_device()
    
    def check_audio_device(self):
        """检查音频设备"""
        temp_audio = pyaudio.PyAudio()
        found = False
        for i in range(temp_audio.get_device_count()):
            dev = temp_audio.get_device_info_by_index(i)
            if 'cable' in dev['name'].lower() and dev['maxInputChannels'] > 0:
                self.device_label.setText(f"检测到的VB-Cable设备: {dev['name']}")
                found = True
                break
        if not found:
            self.device_label.setText("未检测到VB-Cable设备，请先安装VB-Cable")
        temp_audio.terminate()
    
    def refresh_processes(self):
        """刷新进程列表"""
        self.process_combo.clear()
        processes = {}
        for proc in psutil.process_iter(['name', 'pid']):
            name = proc.info['name']
            if name and name not in processes:
                processes[name] = proc.info['pid']
        
        for name in sorted(processes.keys()):
            self.process_combo.addItem(name)
    
    def audio_callback(self, in_data, frame_count, time_info, status):
        """音频回调函数"""
        if self.capturer:
            self.capturer.process_audio(in_data)
        return (in_data, pyaudio.paContinue)
    
    def start_capture(self):
        """开始捕获"""
        process_name = self.process_combo.currentText()
        if not process_name:
            QMessageBox.warning(self, "警告", "请先选择目标进程")
            return
        
        try:
            model_path = 'vosk-model-small-cn-0.22'
            if not os.path.exists(model_path):
                reply = QMessageBox.question(self, '模型未找到', 
                                          '未找到离线模型，是否继续使用在线识别?', 
                                          QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.No:
                    return
                model_path = None
            
            self.capturer = ProcessAudioCapturer(model_path=model_path)
            self.capturer.route_process_audio(process_name)
            self.capturer.start_capture(self.audio_callback)
            
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.status_label.setText(f"正在捕获: {process_name}")
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法开始捕获: {str(e)}")
    
    def stop_capture(self):
        """停止捕获"""
        if self.capturer:
            self.capturer.stop_capture()
            self.capturer = None
        
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("已停止捕获")
    
    def update_ui(self):
        """更新UI"""
        if self.capturer:
            while not self.capturer.text_queue.empty():
                text = self.capturer.text_queue.get()
                self.subtitle_display.append(text)
        
        # 更新当前前台进程
        current_process = self.capturer.get_foreground_process() if self.capturer else None
        if current_process:
            self.status_label.setText(f"当前前台进程: {current_process.name()}")

    def closeEvent(self, event):
        """关闭事件"""
        if self.capturer:
            self.capturer.stop_capture()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # 检查Vosk模型
    if not os.path.exists('vosk-model-small-cn-0.22'):
        reply = QMessageBox.question(None, '模型未找到', 
                                   '未找到离线模型(vosk-model-small-cn-0.22)，是否继续?', 
                                   QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.No:
            sys.exit()
    
    window = SubtitleApp()
    window.show()
    sys.exit(app.exec_())