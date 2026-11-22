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
    QTreeWidget, QTreeWidgetItem, QHeaderView, QSplitter, QToolTip,
    QStyledItemDelegate, QStyle, QListView, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize, QRect
from PyQt5.QtGui import (
    QFont, QTextCursor, QColor, QPalette, QIcon, 
    QStandardItemModel, QStandardItem, QPixmap, QPainter
)

# ======================== 专业级配置 ========================
class AppConfig:
    def __init__(self):
        self.config_file = "professional_capturer_config.json"
        self.defaults = {
            "model_path": os.path.join("models", "vosk-model-small-cn-0.22"),
            "sample_rate": 48000,
            "chunk_size": 2048,
            "auto_route": False,
            "theme": "dark",
            "font": {"family": "Segoe UI", "size": 12},
            "recent_processes": [],
            "audio_settings": {
                "noise_reduction": True,
                "gain": 1.2,
                "silence_threshold": 0.03
            },
            "ui": {
                "show_icons": True,
                "smooth_scrolling": True,
                "animation_enabled": True
            }
        }
        self.config = self.load_config()

    def load_config(self):
        """加载配置文件"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # 深度合并配置
                    return self.deep_merge(self.defaults, config)
            except Exception as e:
                print(f"配置加载失败: {e}")
        return self.defaults.copy()

    def save_config(self):
        """保存配置文件"""
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"配置保存失败: {e}")

    def deep_merge(self, base, update):
        """深度合并字典"""
        for key, value in update.items():
            if isinstance(value, dict) and key in base:
                base[key] = self.deep_merge(base[key], value)
            else:
                base[key] = value
        return base

# ======================== 专业音频引擎 ========================
class ProfessionalAudioEngine:
    def __init__(self, config):
        self.config = config
        self.audio = pyaudio.PyAudio()
        self.stream = None
        self.model = None
        self.recognizer = None
        self.setup_audio()

    def setup_audio(self):
        """初始化音频设备"""
        try:
            # 加载语音模型
            if os.path.exists(self.config['model_path']):
                self.model = Model(self.config['model_path'])
            
            # 配置音频设备
            self.find_best_device()
            
        except Exception as e:
            raise Exception(f"音频初始化失败: {str(e)}")

    def find_best_device(self):
        """自动选择最佳音频设备"""
        devices = self.list_devices()
        # 优先选择VB-Cable
        for dev in devices:
            if 'cable' in dev['name'].lower():
                return self.setup_stream(dev)
        
        # 次选默认输入设备
        default_dev = self.audio.get_default_input_device_info()
        return self.setup_stream(default_dev)

    def setup_stream(self, device_info):
        """配置音频流"""
        self.stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=min(2, device_info['maxInputChannels']),
            rate=self.config['sample_rate'],
            input=True,
            input_device_index=device_info['index'],
            frames_per_buffer=self.config['chunk_size'],
            stream_callback=self.audio_callback
        )
        return self.stream

    def audio_callback(self, in_data, frame_count, time_info, status):
        """专业级音频处理回调"""
        if self.recognizer and self.recognizer.AcceptWaveform(in_data):
            result = json.loads(self.recognizer.Result())
            return result.get('text', '')
        return None

    def list_devices(self):
        """获取所有音频设备"""
        devices = []
        for i in range(self.audio.get_device_count()):
            dev = self.audio.get_device_info_by_index(i)
            if dev['maxInputChannels'] > 0:
                devices.append(dev)
        return devices

    def release(self):
        """释放资源"""
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        self.audio.terminate()

# ======================== 进程管理器 ========================
class ProcessManager:
    @staticmethod
    def get_process_list():
        """获取带窗口的进程列表（含图标）"""
        process_map = {}
        
        def enum_windows_callback(hwnd, extra):
            if win32gui.IsWindowVisible(hwnd):
                try:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    proc = psutil.Process(pid)
                    title = win32gui.GetWindowText(hwnd)
                    if title and proc.name() not in ['ApplicationFrameHost']:
                        if pid not in process_map:
                            process_map[pid] = {
                                'name': proc.name(),
                                'pid': pid,
                                'exe': proc.exe(),
                                'windows': [],
                                'icon': None
                            }
                        process_map[pid]['windows'].append({
                            'hwnd': hwnd,
                            'title': title
                        })
                except Exception:
                    pass
            return True
        
        win32gui.EnumWindows(enum_windows_callback, None)
        return process_map

# ======================== 专业UI组件 ========================
class ProcessItemDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        # 自定义绘制进程项
        painter.save()
        
        # 绘制背景
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, QColor(66, 135, 245))
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(option.rect, QColor(240, 240, 240))
        
        # 绘制图标和文本
        icon = index.data(Qt.DecorationRole)
        text = index.data(Qt.DisplayRole)
        
        icon_rect = QRect(option.rect.x() + 5, 
                         option.rect.y() + (option.rect.height() - 32) // 2,
                         32, 32)
        
        text_rect = QRect(option.rect.x() + 42,
                         option.rect.y(),
                         option.rect.width() - 42,
                         option.rect.height())
        
        if icon:
            painter.drawPixmap(icon_rect, icon.pixmap(32, 32))
        
        painter.setPen(QColor(50, 50, 50))
        painter.drawText(text_rect, Qt.AlignVCenter, text)
        
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(200, 40)

# ======================== 主界面 ========================
class ProfessionalCapturerUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = AppConfig()
        self.audio_engine = None
        self.setup_ui()
        self.setup_connections()
        self.load_settings()

    def setup_ui(self):
        """专业级UI初始化"""
        self.setWindowTitle('专业进程音频转字幕工具')
        self.setWindowIcon(QIcon("assets/icon.ico"))
        self.resize(1200, 800)
        
        # 主布局
        main_widget = QWidget()
        self.main_layout = QHBoxLayout(main_widget)
        self.setCentralWidget(main_widget)
        
        # 左侧控制面板
        self.setup_control_panel()
        
        # 右侧主区域
        self.setup_main_panel()
        
        # 状态栏
        self.setup_status_bar()

    def setup_control_panel(self):
        """专业控制面板"""
        control_panel = QWidget()
        control_panel.setFixedWidth(300)
        control_layout = QVBoxLayout(control_panel)
        
        # 音频设备组
        audio_group = QGroupBox("音频设置")
        audio_layout = QVBoxLayout()
        
        self.device_combo = QComboBox()
        self.sample_rate_combo = QComboBox()
        self.sample_rate_combo.addItems(["44100", "48000", "16000"])
        
        audio_layout.addWidget(QLabel("输入设备:"))
        audio_layout.addWidget(self.device_combo)
        audio_layout.addWidget(QLabel("采样率:"))
        audio_layout.addWidget(self.sample_rate_combo)
        audio_group.setLayout(audio_layout)
        
        # 进程选择组
        process_group = QGroupBox("目标进程")
        process_layout = QVBoxLayout()
        
        self.process_list = QListView()
        self.process_list.setItemDelegate(ProcessItemDelegate())
        self.process_list.setModel(QStandardItemModel())
        self.process_list.setIconSize(QSize(32, 32))
        
        process_layout.addWidget(self.process_list)
        process_group.setLayout(process_layout)
        
        # 控制按钮
        self.start_btn = QPushButton(QIcon("assets/start.png"), "开始捕获")
        self.stop_btn = QPushButton(QIcon("assets/stop.png"), "停止捕获")
        self.stop_btn.setEnabled(False)
        
        # 组装控制面板
        control_layout.addWidget(audio_group)
        control_layout.addWidget(process_group)
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.stop_btn)
        control_layout.addStretch()
        
        self.main_layout.addWidget(control_panel)

    def setup_main_panel(self):
        """专业主显示区"""
        main_panel = QWidget()
        main_panel_layout = QVBoxLayout(main_panel)
        
        # 字幕显示区
        self.subtitle_display = QTextEdit()
        self.subtitle_display.setReadOnly(True)
        self.subtitle_display.setStyleSheet("""
            QTextEdit {
                background-color: #f8f8f8;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 10px;
                font-family: 'Segoe UI', 'Microsoft YaHei';
            }
        """)
        
        # 工具栏
        toolbar = QHBoxLayout()
        self.clear_btn = QPushButton(QIcon("assets/clear.png"), "清空")
        self.save_btn = QPushButton(QIcon("assets/save.png"), "保存")
        
        toolbar.addWidget(self.clear_btn)
        toolbar.addWidget(self.save_btn)
        toolbar.addStretch()
        
        main_panel_layout.addLayout(toolbar)
        main_panel_layout.addWidget(self.subtitle_display)
        
        self.main_layout.addWidget(main_panel, stretch=1)

    def setup_status_bar(self):
        """专业状态栏"""
        self.status_bar = self.statusBar()
        
        # CPU使用率指示器
        self.cpu_label = QLabel()
        self.mem_label = QLabel()
        self.status_label = QLabel("就绪")
        
        self.status_bar.addPermanentWidget(self.cpu_label)
        self.status_bar.addPermanentWidget(self.mem_label)
        self.status_bar.addWidget(self.status_label)

    def setup_connections(self):
        """信号槽连接"""
        self.start_btn.clicked.connect(self.start_capture)
        self.stop_btn.clicked.connect(self.stop_capture)
        self.clear_btn.clicked.connect(self.clear_subtitles)
        self.save_btn.clicked.connect(self.save_subtitles)
        
        # 状态更新定时器
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(1000)

    def load_settings(self):
        """加载设置"""
        # 加载字体
        font = QFont()
        font.setFamily(self.config.config['font']['family'])
        font.setPointSize(self.config.config['font']['size'])
        self.setFont(font)
        
        # 加载主题
        self.apply_theme(self.config.config['theme'])
        
        # 加载音频设备
        self.refresh_audio_devices()
        
        # 加载进程列表
        self.refresh_process_list()

    def apply_theme(self, theme_name):
        """应用专业主题"""
        palette = self.palette()
        
        if theme_name == "dark":
            palette.setColor(QPalette.Window, QColor(45, 45, 45))
            palette.setColor(QPalette.WindowText, Qt.white)
            palette.setColor(QPalette.Base, QColor(30, 30, 30))
            palette.setColor(QPalette.AlternateBase, QColor(45, 45, 45))
            palette.setColor(QPalette.ToolTipBase, Qt.white)
            palette.setColor(QPalette.ToolTipText, Qt.white)
            palette.setColor(QPalette.Text, Qt.white)
            palette.setColor(QPalette.Button, QColor(60, 60, 60))
            palette.setColor(QPalette.ButtonText, Qt.white)
            palette.setColor(QPalette.BrightText, Qt.red)
            palette.setColor(QPalette.Highlight, QColor(66, 135, 245))
            palette.setColor(QPalette.HighlightedText, Qt.white)
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
        
        self.setPalette(palette)
        
        # 额外样式
        self.setStyleSheet("""
            QGroupBox {
                border: 1px solid #444;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 15px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
            }
            QPushButton {
                padding: 5px 10px;
                border-radius: 4px;
                min-width: 80px;
            }
            QComboBox, QListView {
                border: 1px solid #ccc;
                border-radius: 4px;
                padding: 2px;
            }
        """)

    def refresh_audio_devices(self):
        """刷新音频设备列表"""
        self.device_combo.clear()
        try:
            audio = pyaudio.PyAudio()
            for i in range(audio.get_device_count()):
                dev = audio.get_device_info_by_index(i)
                if dev['maxInputChannels'] > 0:
                    self.device_combo.addItem(
                        f"{dev['name']} (Ch: {dev['maxInputChannels']})",
                        userData=dev
                    )
            audio.terminate()
        except Exception as e:
            print(f"设备刷新失败: {e}")

    def refresh_process_list(self):
        """刷新进程列表"""
        model = self.process_list.model()
        model.clear()
        
        try:
            processes = ProcessManager.get_process_list()
            for pid, proc in processes.items():
                item = QStandardItem()
                item.setText(f"{proc['name']} (PID: {pid})")
                item.setData(pid, Qt.UserRole)
                
                # 尝试加载图标
                if os.path.exists(proc['exe']):
                    icon = QIcon(proc['exe'])
                    item.setIcon(icon)
                
                model.appendRow(item)
        except Exception as e:
            print(f"进程刷新失败: {e}")

    def update_status(self):
        """更新状态信息"""
        cpu_percent = psutil.cpu_percent()
        mem = psutil.virtual_memory()
        
        self.cpu_label.setText(f"CPU: {cpu_percent}%")
        self.mem_label.setText(f"内存: {mem.percent}%")

    def start_capture(self):
        """开始捕获音频"""
        selected_index = self.process_list.currentIndex()
        if not selected_index.isValid():
            QMessageBox.warning(self, "警告", "请先选择目标进程")
            return
        
        pid = selected_index.data(Qt.UserRole)
        self.status_label.setText(f"正在初始化音频捕获 (PID: {pid})...")
        
        try:
            self.audio_engine = ProfessionalAudioEngine(self.config.config)
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.status_label.setText(f"正在捕获 PID: {pid} 的音频...")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"捕获启动失败: {str(e)}")
            self.status_label.setText("捕获启动失败")

    def stop_capture(self):
        """停止捕获音频"""
        if self.audio_engine:
            self.audio_engine.release()
            self.audio_engine = None
        
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("捕获已停止")

    def clear_subtitles(self):
        """清空字幕"""
        self.subtitle_display.clear()

    def save_subtitles(self):
        """保存字幕"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存字幕", "", "文本文件 (*.txt);;所有文件 (*)"
        )
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(self.subtitle_display.toPlainText())
                self.status_label.setText(f"字幕已保存到: {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存失败: {str(e)}")

    def closeEvent(self, event):
        """关闭事件处理"""
        self.stop_capture()
        self.config.save_config()
        event.accept()

# ======================== 启动应用 ========================
if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # 设置应用程序样式
    app.setStyle('Fusion')
    
    # 检查必要组件
    if not os.path.exists("models/vosk-model-small-cn-0.22"):
        reply = QMessageBox.question(
            None, '缺少语音模型',
            '未找到语音识别模型，是否从官网下载？',
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            import webbrowser
            webbrowser.open("https://alphacephei.com/vosk/models")
    
    window = ProfessionalCapturerUI()
    window.show()
    sys.exit(app.exec_())