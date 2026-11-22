import os
import sys
import json
import queue
import time
import psutil
import pyaudio
import win32gui
import win32process
import win32com.client
import pythoncom
from vosk import Model, KaldiRecognizer
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel, QTextEdit,
    QPushButton, QComboBox, QCheckBox, QHBoxLayout, QMessageBox, QGroupBox,
    QSpinBox, QDoubleSpinBox, QFileDialog, QTabWidget, QScrollArea,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QSplitter, QToolTip
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize
from PyQt5.QtGui import QFont, QTextCursor, QColor, QPalette, QIcon

# ======================== 全局配置 ========================
CONFIG_FILE = "audio_capturer_config.json"
DEFAULT_CONFIG = {
    "model_path": "vosk-model-small-cn-0.22",
    "sample_rate": 44100,
    "chunk_size": 1024,
    "auto_route": False,
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
    "show_window_titles": True,
    "show_process_icons": True,
    "auto_scroll": True
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

class ProcessUtils:
    @staticmethod
    def get_all_windows():
        """获取所有窗口及其所属进程信息"""
        windows = []
        
        def callback(hwnd, extra):
            if win32gui.IsWindowVisible(hwnd):
                try:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    proc = psutil.Process(pid)
                    title = win32gui.GetWindowText(hwnd)
                    if title:  # 只收集有标题的窗口
                        windows.append({
                            'hwnd': hwnd,
                            'pid': pid,
                            'title': title,
                            'process_name': proc.name(),
                            'exe_path': proc.exe(),
                            'icon': None
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            return True
        
        win32gui.EnumWindows(callback, None)
        return windows

    @staticmethod
    def get_process_icon(process_path):
        """获取进程图标"""
        try:
            ico_x = win32api.GetSystemMetrics(win32con.SM_CXSMICON)
            ico_y = win32api.GetSystemMetrics(win32con.SM_CYSMICON)
            large, small = win32gui.ExtractIconEx(process_path, 0)
            win32gui.DestroyIcon(large[0])
            return small[0]
        except:
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
        self.setWindowIcon(QIcon("icon.ico"))  # 请准备一个图标文件

    def init_ui(self):
        self.setWindowTitle('高级进程音频监听转字幕工具')
        self.setGeometry(100, 100, 1200, 800)

        # 主部件和布局
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        
        # 使用分割器创建更灵活的布局
        splitter = QSplitter(Qt.Vertical)
        
        # 上部控制面板
        control_panel = QWidget()
        control_layout = QVBoxLayout()
        
        # 设备信息组
        device_group = QGroupBox("音频设备状态")
        device_layout = QVBoxLayout()
        
        self.device_status_label = QLabel()
        self.device_status_label.setWordWrap(True)
        self.refresh_devices_btn = QPushButton(QIcon("refresh.png"), "刷新设备状态")
        self.refresh_devices_btn.clicked.connect(self.refresh_devices)
        
        device_layout.addWidget(self.device_status_label)
        device_layout.addWidget(self.refresh_devices_btn)
        device_group.setLayout(device_layout)
        control_layout.addWidget(device_group)
        
        # 进程选择组
        process_group = QGroupBox("选择目标进程")
        process_layout = QVBoxLayout()
        
        # 使用树形控件显示进程
        self.process_tree = QTreeWidget()
        self.process_tree.setHeaderLabels(["进程", "PID", "窗口标题"])
        self.process_tree.setColumnCount(3)
        self.process_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.process_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.process_tree.header().setSectionResizeMode(2, QHeaderView.Stretch)
        self.process_tree.setSortingEnabled(True)
        self.process_tree.sortByColumn(0, Qt.AscendingOrder)
        self.process_tree.itemDoubleClicked.connect(self.select_process)
        
        self.refresh_processes_btn = QPushButton(QIcon("refresh.png"), "刷新进程列表")
        self.refresh_processes_btn.clicked.connect(self.refresh_processes)
        
        process_layout.addWidget(self.process_tree)
        process_layout.addWidget(self.refresh_processes_btn)
        process_group.setLayout(process_layout)
        control_layout.addWidget(process_group)
        
        # 控制按钮组
        btn_group = QWidget()
        btn_layout = QHBoxLayout()
        
        self.start_btn = QPushButton(QIcon("start.png"), "开始捕获")
        self.start_btn.clicked.connect(self.start_capture)
        self.stop_btn = QPushButton(QIcon("stop.png"), "停止捕获")
        self.stop_btn.clicked.connect(self.stop_capture)
        self.stop_btn.setEnabled(False)
        
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        btn_group.setLayout(btn_layout)
        control_layout.addWidget(btn_group)
        
        control_panel.setLayout(control_layout)
        splitter.addWidget(control_panel)
        
        # 下部字幕面板
        subtitle_panel = QWidget()
        subtitle_layout = QVBoxLayout()
        
        # 字幕工具栏
        subtitle_toolbar = QHBoxLayout()
        
        self.clear_btn = QPushButton(QIcon("clear.png"), "清空字幕")
        self.clear_btn.clicked.connect(self.clear_subtitles)
        self.save_btn = QPushButton(QIcon("save.png"), "保存字幕")
        self.save_btn.clicked.connect(self.save_subtitles)
        
        subtitle_toolbar.addWidget(self.clear_btn)
        subtitle_toolbar.addWidget(self.save_btn)
        subtitle_toolbar.addStretch()
        
        # 字幕显示区域
        self.subtitle_display = QTextEdit()
        self.subtitle_display.setReadOnly(True)
        self.subtitle_display.setFont(QFont("Microsoft YaHei", self.config['font_size']))
        self.subtitle_display.setLineWrapMode(QTextEdit.NoWrap)
        
        subtitle_layout.addLayout(subtitle_toolbar)
        subtitle_layout.addWidget(self.subtitle_display)
        subtitle_panel.setLayout(subtitle_layout)
        splitter.addWidget(subtitle_panel)
        
        # 设置分割器初始比例
        splitter.setSizes([300, 500])
        
        main_layout.addWidget(splitter)
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)
        
        # 状态栏
        self.status_bar = self.statusBar()
        self.status_label = QLabel("就绪")
        self.status_bar.addPermanentWidget(self.status_label)
        
        # 初始化
        self.refresh_devices()
        self.refresh_processes()
        
        # 定时器
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_status)
        self.timer.start(1000)

    def setup_theme(self):
        """设置界面主题"""
        palette = self.palette()
        
        if self.config['theme'] == 'dark':
            palette.setColor(QPalette.Window, QColor(53, 53, 53))
            palette.setColor(QPalette.WindowText, Qt.white)
            palette.setColor(QPalette.Base, QColor(35, 35, 35))
            palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
            palette.setColor(QPalette.ToolTipBase, QColor(25, 25, 25))
            palette.setColor(QPalette.ToolTipText, Qt.white)
            palette.setColor(QPalette.Text, Qt.white)
            palette.setColor(QPalette.Button, QColor(53, 53, 53))
            palette.setColor(QPalette.ButtonText, Qt.white)
            palette.setColor(QPalette.BrightText, Qt.red)
            palette.setColor(QPalette.Highlight, QColor(142, 45, 197).lighter())
            palette.setColor(QPalette.HighlightedText, Qt.black)
            
            self.setStyleSheet("""
                QGroupBox {
                    border: 1px solid #444;
                    border-radius: 3px;
                    margin-top: 10px;
                    padding-top: 15px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 3px;
                }
                QTreeWidget {
                    border: 1px solid #444;
                    border-radius: 3px;
                }
                QTextEdit {
                    border: 1px solid #444;
                    border-radius: 3px;
                }
            """)
        else:
            palette.setColor(QPalette.Window, QColor(240, 240, 240))
            palette.setColor(QPalette.WindowText, Qt.black)
            palette.setColor(QPalette.Base, Qt.white)
            palette.setColor(QPalette.AlternateBase, QColor(240, 240, 240))
            palette.setColor(QPalette.ToolTipBase, Qt.white)
            palette.setColor(QPalette.ToolTipText, Qt.black)
            palette.setColor(QPalette.Text, Qt.black)
            palette.setColor(QPalette.Button, QColor(240, 240, 240))
            palette.setColor(QPalette.ButtonText, Qt.black)
            palette.setColor(QPalette.BrightText, Qt.red)
            palette.setColor(QPalette.Highlight, QColor(66, 135, 245))
            palette.setColor(QPalette.HighlightedText, Qt.white)
            
            self.setStyleSheet("""
                QGroupBox {
                    border: 1px solid #ccc;
                    border-radius: 3px;
                    margin-top: 10px;
                    padding-top: 15px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 3px;
                }
                QTreeWidget {
                    border: 1px solid #ccc;
                    border-radius: 3px;
                }
                QTextEdit {
                    border: 1px solid #ccc;
                    border-radius: 3px;
                }
            """)
        
        self.setPalette(palette)
        QToolTip.setPalette(palette)

    def refresh_devices(self):
        """刷新音频设备列表"""
        vb_cable = AudioUtils.find_vb_cable()
        if vb_cable:
            self.device_status_label.setText(
                f"<b>VB-Cable状态:</b> <span style='color:green'>已安装</span><br>"
                f"<b>设备名称:</b> {vb_cable['name']}<br>"
                f"<b>输入声道:</b> {vb_cable['input_channels']}<br>"
                f"<b>默认采样率:</b> {vb_cable['default_rate']}Hz"
            )
        else:
            self.device_status_label.setText(
                f"<b>VB-Cable状态:</b> <span style='color:red'>未检测到</span><br>"
                "请安装VB-Cable虚拟音频设备并确保已启用"
            )

    def refresh_processes(self):
        """刷新进程列表"""
        self.process_tree.clear()
        windows = ProcessUtils.get_all_windows()
        
        # 按进程名分组
        process_map = {}
        for window in windows:
            if window['process_name'] not in process_map:
                process_map[window['process_name']] = []
            process_map[window['process_name']].append(window)
        
        # 添加到树形控件
        for process_name, windows in process_map.items():
            process_item = QTreeWidgetItem(self.process_tree)
            process_item.setText(0, process_name)
            process_item.setText(1, str(windows[0]['pid']))
            process_item.setData(0, Qt.UserRole, windows[0]['pid'])
            
            # 如果有多个窗口，添加子项
            if len(windows) > 1 or self.config['show_window_titles']:
                for window in windows:
                    window_item = QTreeWidgetItem(process_item)
                    window_item.setText(0, window['title'])
                    window_item.setText(1, str(window['pid']))
                    window_item.setText(2, window['title'])
                    window_item.setData(0, Qt.UserRole, window['pid'])
        
        self.process_tree.expandAll()

    def select_process(self, item, column):
        """选择进程"""
        if item.childCount() == 0:  # 选择的是窗口项
            pid = item.data(0, Qt.UserRole)
            self.status_label.setText(f"已选择: {item.text(0)} (PID: {pid})")

    def update_status(self):
        """更新状态栏信息"""
        if self.capture_thread and self.capture_thread.isRunning():
            self.status_label.setText("状态: 正在捕获音频...")
        else:
            # 显示系统信息
            cpu_percent = psutil.cpu_percent()
            mem = psutil.virtual_memory()
            self.status_label.setText(
                f"CPU使用率: {cpu_percent}% | "
                f"内存使用: {mem.used//1024//1024}MB/{mem.total//1024//1024}MB"
            )

    def start_capture(self):
        """开始捕获音频"""
        current_item = self.process_tree.currentItem()
        if not current_item:
            QMessageBox.warning(self, "警告", "请先选择目标进程或窗口")
            return

        pid = current_item.data(0, Qt.UserRole)
        
        # 创建配置
        config = self.config.copy()
        config['target_pid'] = pid
        
        # 启动捕获线程
        self.capture_thread = AudioCaptureThread(config)
        self.capture_thread.update_signal.connect(self.update_subtitle)
        self.capture_thread.error_signal.connect(self.show_error)
        self.capture_thread.status_signal.connect(self.update_status)
        self.capture_thread.finished.connect(self.capture_finished)
        
        self.capture_thread.start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText(f"正在捕获 PID: {pid} 的音频...")

    def stop_capture(self):
        """停止捕获音频"""
        if self.capture_thread:
            self.capture_thread.stop()
            self.stop_btn.setEnabled(False)

    def capture_finished(self):
        """捕获线程完成"""
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("捕获已停止")

    def update_subtitle(self, text):
        """更新字幕显示"""
        cursor = self.subtitle_display.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text + "\n")
        
        if self.config['auto_scroll']:
            self.subtitle_display.ensureCursorVisible()

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

    def show_error(self, message):
        """显示错误信息"""
        QMessageBox.critical(self, "错误", message)

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