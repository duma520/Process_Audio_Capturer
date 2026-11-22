import os
import sys
import json
import queue
import time
import psutil
import pyaudio
import wave
import requests
import threading
import sounddevice as sd
import win32gui
import win32process
import win32com.client
import pythoncom
from vosk import Model, KaldiRecognizer
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel, QTextEdit,
    QPushButton, QComboBox, QCheckBox, QHBoxLayout, QMessageBox, QGroupBox,
    QSpinBox, QDoubleSpinBox, QFileDialog, QProgressBar, QTabWidget, QScrollArea
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QTextCursor, QColor, QPalette

# ======================== 全局配置 ========================
CONFIG_FILE = "audio_capturer_config.json"
DEFAULT_CONFIG = {
    "model_path": "vosk-model-small-cn-0.22",
    "sample_rate": 44100,
    "chunk_size": 1024,
    "auto_route": True,
    "save_logs": True,
    "log_dir": "logs",
    "theme": "dark",
    "font_size": 12,
    "target_process": "",
    "language": "zh-cn",
    "api_key": "",
    "proxy": "",
    "noise_reduction": True,
    "gain_level": 1.0,
    "hotkeys": {
        "start_capture": "Ctrl+Alt+S",
        "stop_capture": "Ctrl+Alt+X"
    }
}

# ======================== 工具类 ========================
class AudioUtils:
    @staticmethod
    def list_audio_devices():
        """获取所有音频设备"""
        p = pyaudio.PyAudio()
        devices = []
        for i in range(p.get_device_count()):
            dev = p.get_device_info_by_index(i)
            devices.append({
                'index': i,
                'name': dev['name'],
                'input_channels': dev['maxInputChannels'],
                'output_channels': dev['maxOutputChannels'],
                'default_rate': dev['defaultSampleRate']
            })
        p.terminate()
        return devices

    @staticmethod
    def find_vb_cable():
        """查找VB-Cable设备"""
        devices = AudioUtils.list_audio_devices()
        for dev in devices:
            if 'cable' in dev['name'].lower():
                return dev
        return None

    @staticmethod
    def set_default_playback(device_name):
        """设置默认播放设备 (需要管理员权限)"""
        try:
            pythoncom.CoInitialize()
            audio_mgr = win32com.client.Dispatch("AudioEndpointManager")
            audio_mgr.SetDefaultDevice(device_name, 0)  # 0 for playback
            return True
        except Exception as e:
            print(f"设置默认设备失败: {e}")
            return False

class ProcessUtils:
    @staticmethod
    def list_processes():
        """获取所有运行中的进程"""
        processes = []
        for proc in psutil.process_iter(['name', 'pid', 'exe']):
            try:
                processes.append({
                    'name': proc.info['name'],
                    'pid': proc.info['pid'],
                    'path': proc.info['exe']
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return sorted(processes, key=lambda x: x['name'])

    @staticmethod
    def get_foreground_process():
        """获取当前前台进程"""
        window = win32gui.GetForegroundWindow()
        pid = win32process.GetWindowThreadProcessId(window)[1]
        try:
            proc = psutil.Process(pid)
            return {
                'name': proc.name(),
                'pid': pid,
                'path': proc.exe()
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

# ======================== 工作线程 ========================
class AudioCaptureThread(QThread):
    update_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.running = False
        self.audio = None
        self.stream = None
        self.model = None
        self.recognizer = None

    def run(self):
        try:
            self.running = True
            self.status_signal.emit("正在初始化音频捕获...")

            # 加载语音识别模型
            if os.path.exists(self.config['model_path']):
                self.model = Model(self.config['model_path'])
                self.recognizer = KaldiRecognizer(self.model, self.config['sample_rate'])
                self.recognizer.SetWords(True)
            else:
                self.error_signal.emit("未找到语音识别模型")
                return

            # 初始化音频流
            self.audio = pyaudio.PyAudio()
            vb_cable = AudioUtils.find_vb_cable()
            if not vb_cable:
                self.error_signal.emit("未找到VB-Cable设备")
                return

            self.stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=min(2, vb_cable['input_channels']),
                rate=self.config['sample_rate'],
                input=True,
                input_device_index=vb_cable['index'],
                frames_per_buffer=self.config['chunk_size'],
                stream_callback=self.audio_callback,
                start=False
            )

            self.stream.start_stream()
            self.status_signal.emit(f"正在捕获音频... (PID: {os.getpid()})")

            while self.running:
                time.sleep(0.1)

        except Exception as e:
            self.error_signal.emit(f"捕获线程错误: {str(e)}")
        finally:
            self.cleanup()

    def audio_callback(self, in_data, frame_count, time_info, status):
        if self.running and self.recognizer:
            if self.recognizer.AcceptWaveform(in_data):
                result = json.loads(self.recognizer.Result())
                text = result.get('text', '')
                if text:
                    self.update_signal.emit(text)
        return (in_data, pyaudio.paContinue)

    def stop(self):
        self.running = False
        self.status_signal.emit("正在停止捕获...")

    def cleanup(self):
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        if self.audio:
            self.audio.terminate()
        self.status_signal.emit("捕获已停止")

# ======================== 主界面 ========================
class AudioCapturerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = self.load_config()
        self.capture_thread = None
        self.init_ui()
        self.setup_theme()

    def init_ui(self):
        self.setWindowTitle('高级进程音频监听转字幕工具')
        self.setGeometry(100, 100, 1000, 800)

        # 主部件和布局
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        
        # 标签页
        tab_widget = QTabWidget()
        
        # 1. 控制标签页
        control_tab = QWidget()
        control_layout = QVBoxLayout()
        
        # 设备信息组
        device_group = QGroupBox("音频设备信息")
        device_layout = QVBoxLayout()
        
        self.device_info_label = QLabel("VB-Cable状态: 未检测到")
        self.device_refresh_btn = QPushButton("刷新设备")
        self.device_refresh_btn.clicked.connect(self.refresh_devices)
        
        device_layout.addWidget(self.device_info_label)
        device_layout.addWidget(self.device_refresh_btn)
        device_group.setLayout(device_layout)
        control_layout.addWidget(device_group)
        
        # 进程选择组
        process_group = QGroupBox("目标进程")
        process_layout = QVBoxLayout()
        
        self.process_combo = QComboBox()
        self.process_refresh_btn = QPushButton("刷新进程列表")
        self.process_refresh_btn.clicked.connect(self.refresh_processes)
        self.auto_route_check = QCheckBox("自动路由音频(需要管理员权限)")
        self.auto_route_check.setChecked(self.config['auto_route'])
        
        process_layout.addWidget(QLabel("选择目标进程:"))
        process_layout.addWidget(self.process_combo)
        process_layout.addWidget(self.process_refresh_btn)
        process_layout.addWidget(self.auto_route_check)
        process_group.setLayout(process_layout)
        control_layout.addWidget(process_group)
        
        # 控制按钮组
        btn_group = QWidget()
        btn_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("开始捕获")
        self.start_btn.clicked.connect(self.start_capture)
        self.stop_btn = QPushButton("停止捕获")
        self.stop_btn.clicked.connect(self.stop_capture)
        self.stop_btn.setEnabled(False)
        
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        btn_group.setLayout(btn_layout)
        control_layout.addWidget(btn_group)
        
        # 状态栏
        self.status_bar = QLabel("就绪")
        self.status_bar.setAlignment(Qt.AlignCenter)
        control_layout.addWidget(self.status_bar)
        
        control_tab.setLayout(control_layout)
        
        # 2. 字幕显示标签页
        subtitle_tab = QWidget()
        subtitle_layout = QVBoxLayout()
        
        self.subtitle_display = QTextEdit()
        self.subtitle_display.setReadOnly(True)
        self.subtitle_display.setFont(QFont("Microsoft YaHei", self.config['font_size']))
        
        subtitle_toolbar = QHBoxLayout()
        self.clear_btn = QPushButton("清空字幕")
        self.clear_btn.clicked.connect(self.clear_subtitles)
        self.save_btn = QPushButton("保存字幕")
        self.save_btn.clicked.connect(self.save_subtitles)
        
        subtitle_toolbar.addWidget(self.clear_btn)
        subtitle_toolbar.addWidget(self.save_btn)
        
        subtitle_layout.addLayout(subtitle_toolbar)
        subtitle_layout.addWidget(self.subtitle_display)
        subtitle_tab.setLayout(subtitle_layout)
        
        # 3. 设置标签页
        settings_tab = QWidget()
        settings_layout = QVBoxLayout()
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout()
        
        # 模型设置
        model_group = QGroupBox("语音识别设置")
        model_layout = QVBoxLayout()
        
        self.model_path_edit = QTextEdit()
        self.model_path_edit.setPlainText(self.config['model_path'])
        self.model_path_edit.setMaximumHeight(60)
        self.browse_model_btn = QPushButton("浏览模型路径")
        self.browse_model_btn.clicked.connect(self.browse_model_path)
        
        model_layout.addWidget(QLabel("模型路径:"))
        model_layout.addWidget(self.model_path_edit)
        model_layout.addWidget(self.browse_model_btn)
        model_group.setLayout(model_layout)
        scroll_layout.addWidget(model_group)
        
        # 音频设置
        audio_group = QGroupBox("音频设置")
        audio_layout = QVBoxLayout()
        
        self.sample_rate_spin = QSpinBox()
        self.sample_rate_spin.setRange(8000, 48000)
        self.sample_rate_spin.setValue(self.config['sample_rate'])
        
        self.chunk_size_spin = QSpinBox()
        self.chunk_size_spin.setRange(256, 4096)
        self.chunk_size_spin.setValue(self.config['chunk_size'])
        
        self.noise_reduction_check = QCheckBox("启用降噪")
        self.noise_reduction_check.setChecked(self.config['noise_reduction'])
        
        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setRange(0.1, 5.0)
        self.gain_spin.setValue(self.config['gain_level'])
        self.gain_spin.setSingleStep(0.1)
        
        audio_layout.addWidget(QLabel("采样率:"))
        audio_layout.addWidget(self.sample_rate_spin)
        audio_layout.addWidget(QLabel("块大小:"))
        audio_layout.addWidget(self.chunk_size_spin)
        audio_layout.addWidget(self.noise_reduction_check)
        audio_layout.addWidget(QLabel("增益:"))
        audio_layout.addWidget(self.gain_spin)
        audio_group.setLayout(audio_layout)
        scroll_layout.addWidget(audio_group)
        
        # 界面设置
        ui_group = QGroupBox("界面设置")
        ui_layout = QVBoxLayout()
        
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["dark", "light"])
        self.theme_combo.setCurrentText(self.config['theme'])
        
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 24)
        self.font_size_spin.setValue(self.config['font_size'])
        
        ui_layout.addWidget(QLabel("主题:"))
        ui_layout.addWidget(self.theme_combo)
        ui_layout.addWidget(QLabel("字体大小:"))
        ui_layout.addWidget(self.font_size_spin)
        ui_group.setLayout(ui_layout)
        scroll_layout.addWidget(ui_group)
        
        # 保存按钮
        self.save_settings_btn = QPushButton("保存设置")
        self.save_settings_btn.clicked.connect(self.save_settings)
        scroll_layout.addWidget(self.save_settings_btn)
        
        scroll_content.setLayout(scroll_layout)
        scroll.setWidget(scroll_content)
        settings_layout.addWidget(scroll)
        settings_tab.setLayout(settings_layout)
        
        # 添加标签页
        tab_widget.addTab(control_tab, "控制")
        tab_widget.addTab(subtitle_tab, "字幕")
        tab_widget.addTab(settings_tab, "设置")
        
        main_layout.addWidget(tab_widget)
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)
        
        # 初始化
        self.refresh_devices()
        self.refresh_processes()
        
        # 定时器
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_foreground_process)
        self.timer.start(1000)

    def setup_theme(self):
        """设置界面主题"""
        if self.config['theme'] == 'dark':
            self.setStyleSheet("""
                QMainWindow, QWidget {
                    background-color: #333333;
                    color: #ffffff;
                }
                QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
                    background-color: #444444;
                    color: #ffffff;
                    border: 1px solid #555555;
                }
                QPushButton {
                    background-color: #555555;
                    color: #ffffff;
                    border: 1px solid #666666;
                    padding: 5px;
                }
                QPushButton:hover {
                    background-color: #666666;
                }
                QGroupBox {
                    border: 1px solid #555555;
                    border-radius: 5px;
                    margin-top: 10px;
                    padding-top: 15px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 3px;
                }
            """)
        else:
            self.setStyleSheet("")

    def refresh_devices(self):
        """刷新音频设备列表"""
        vb_cable = AudioUtils.find_vb_cable()
        if vb_cable:
            self.device_info_label.setText(
                f"VB-Cable状态: 已检测到 ({vb_cable['name']})\n"
                f"输入声道: {vb_cable['input_channels']}, "
                f"采样率: {vb_cable['default_rate']}Hz"
            )
        else:
            self.device_info_label.setText("VB-Cable状态: 未检测到\n请安装VB-Cable虚拟音频设备")

    def refresh_processes(self):
        """刷新进程列表"""
        self.process_combo.clear()
        processes = ProcessUtils.list_processes()
        for proc in processes:
            self.process_combo.addItem(f"{proc['name']} (PID: {proc['pid']})", userData=proc)
        
        # 尝试选择前台进程
        fg_proc = ProcessUtils.get_foreground_process()
        if fg_proc:
            for i in range(self.process_combo.count()):
                if self.process_combo.itemData(i)['pid'] == fg_proc['pid']:
                    self.process_combo.setCurrentIndex(i)
                    break

    def update_foreground_process(self):
        """更新当前前台进程显示"""
        fg_proc = ProcessUtils.get_foreground_process()
        if fg_proc:
            self.status_bar.setText(f"当前前台进程: {fg_proc['name']} (PID: {fg_proc['pid']})")

    def start_capture(self):
        """开始捕获音频"""
        if self.capture_thread and self.capture_thread.isRunning():
            return

        selected_proc = self.process_combo.currentData()
        if not selected_proc:
            QMessageBox.warning(self, "警告", "请先选择目标进程")
            return

        # 更新配置
        self.config['target_process'] = selected_proc['name']
        self.config['auto_route'] = self.auto_route_check.isChecked()
        
        # 自动路由音频
        if self.config['auto_route']:
            if not AudioUtils.set_default_playback("CABLE Input (VB-Audio Virtual Cable)"):
                QMessageBox.warning(self, "警告", "自动路由失败，请手动设置音频输出设备")

        # 启动捕获线程
        self.capture_thread = AudioCaptureThread(self.config)
        self.capture_thread.update_signal.connect(self.update_subtitle)
        self.capture_thread.error_signal.connect(self.show_error)
        self.capture_thread.status_signal.connect(self.status_bar.setText)
        self.capture_thread.finished.connect(self.capture_finished)
        
        self.capture_thread.start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def stop_capture(self):
        """停止捕获音频"""
        if self.capture_thread:
            self.capture_thread.stop()
            self.stop_btn.setEnabled(False)

    def capture_finished(self):
        """捕获线程完成"""
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def update_subtitle(self, text):
        """更新字幕显示"""
        self.subtitle_display.moveCursor(QTextCursor.End)
        self.subtitle_display.insertPlainText(text + "\n")
        self.subtitle_display.moveCursor(QTextCursor.End)

    def clear_subtitles(self):
        """清空字幕"""
        self.subtitle_display.clear()

    def save_subtitles(self):
        """保存字幕到文件"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存字幕", "", "文本文件 (*.txt);;所有文件 (*)"
        )
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(self.subtitle_display.toPlainText())
                QMessageBox.information(self, "成功", "字幕已保存")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存失败: {str(e)}")

    def browse_model_path(self):
        """浏览模型路径"""
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择语音识别模型目录", 
            os.path.dirname(self.config['model_path']) or ""
        )
        if dir_path:
            self.model_path_edit.setPlainText(dir_path)

    def save_settings(self):
        """保存设置"""
        self.config.update({
            'model_path': self.model_path_edit.toPlainText(),
            'sample_rate': self.sample_rate_spin.value(),
            'chunk_size': self.chunk_size_spin.value(),
            'noise_reduction': self.noise_reduction_check.isChecked(),
            'gain_level': self.gain_spin.value(),
            'theme': self.theme_combo.currentText(),
            'font_size': self.font_size_spin.value()
        })
        
        self.save_config()
        self.setup_theme()
        self.subtitle_display.setFont(QFont("Microsoft YaHei", self.config['font_size']))
        QMessageBox.information(self, "成功", "设置已保存")

    def show_error(self, message):
        """显示错误信息"""
        QMessageBox.critical(self, "错误", message)

    def load_config(self):
        """加载配置文件"""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # 确保所有必要的键都存在
                    for key in DEFAULT_CONFIG:
                        if key not in config:
                            config[key] = DEFAULT_CONFIG[key]
                    return config
            except:
                pass
        return DEFAULT_CONFIG.copy()

    def save_config(self):
        """保存配置文件"""
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"保存配置失败: {str(e)}")

    def closeEvent(self, event):
        """关闭事件处理"""
        if self.capture_thread and self.capture_thread.isRunning():
            self.capture_thread.stop()
            self.capture_thread.wait(2000)
        
        self.save_config()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # 检查Vosk模型
    if not os.path.exists(DEFAULT_CONFIG['model_path']):
        reply = QMessageBox.question(
            None, '模型未找到', 
            f"未找到语音识别模型({DEFAULT_CONFIG['model_path']})，是否继续?", 
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.No:
            sys.exit()
    
    window = AudioCapturerApp()
    window.show()
    sys.exit(app.exec_())