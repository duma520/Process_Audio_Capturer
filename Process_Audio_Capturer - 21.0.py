import os
import sys
import json
import time
import psutil
import pyaudio
import wave
import requests
import numpy as np
from vosk import Model, KaldiRecognizer
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel, QTextEdit,
    QPushButton, QComboBox, QCheckBox, QHBoxLayout, QMessageBox, QGroupBox,
    QSpinBox, QDoubleSpinBox, QFileDialog, QTabWidget, QScrollArea,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QSplitter, QToolTip,
    QStyledItemDelegate, QStyle, QListView, QSizePolicy, QProgressBar,
    QMenu, QAction, QSystemTrayIcon, QSlider, QColorDialog, QFontDialog
)
from PyQt5.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, QSize, QRect, 
    QPoint, QPropertyAnimation, QEasingCurve
)
from PyQt5.QtGui import (
    QFont, QTextCursor, QColor, QPalette, QIcon, 
    QStandardItemModel, QStandardItem, QPixmap, QPainter,
    QTextCharFormat, QSyntaxHighlighter, QKeySequence
)
from PyQt5 import QtWinExtras

class UltimateAudioTranscriber(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # 初始化配置
        self.config = {
            'theme': 'light',
            'font': {'family': 'Microsoft YaHei', 'size': 12},
            'audio': {
                'input_device': None,
                'sample_rate': 44100,
                'chunk_size': 2048,
                'volume': 80,
                'noise_reduction': True
            },
            'recognition': {
                'model_path': 'models/vosk-model',
                'language': 'zh-CN',
                'online': False
            },
            'ui': {
                'opacity': 100,
                'always_on_top': False,
                'auto_scroll': True
            },
            'shortcuts': {
                'start': 'Ctrl+Alt+S',
                'stop': 'Ctrl+Alt+X'
            }
        }
        
        # 初始化UI
        self.init_ui()
        self.init_menu()
        self.init_tray()
        self.load_settings()
        
        # 初始化音频
        self.audio = pyaudio.PyAudio()
        self.stream = None
        self.is_recording = False
        
        # 初始化模型
        self.model = None
        self.recognizer = None
        self.load_model()
        
        # 初始化状态
        self.update_devices()
        self.update_processes()

    def init_ui(self):
        """初始化主界面"""
        self.setWindowTitle('终极音频转字幕专业版')
        self.setWindowIcon(QIcon('icon.ico'))
        self.resize(1200, 800)
        
        # 主布局
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QHBoxLayout(main_widget)
        
        # 左侧控制面板
        control_panel = QWidget()
        control_panel.setMaximumWidth(350)
        control_layout = QVBoxLayout(control_panel)
        
        # 音频设备组
        audio_group = QGroupBox("音频设置")
        audio_layout = QVBoxLayout()
        
        self.device_combo = QComboBox()
        self.sample_rate_combo = QComboBox()
        self.sample_rate_combo.addItems(['8000', '11025', '16000', '22050', '44100', '48000'])
        
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        
        audio_layout.addWidget(QLabel("输入设备:"))
        audio_layout.addWidget(self.device_combo)
        audio_layout.addWidget(QLabel("采样率:"))
        audio_layout.addWidget(self.sample_rate_combo)
        audio_layout.addWidget(QLabel("音量:"))
        audio_layout.addWidget(self.volume_slider)
        audio_group.setLayout(audio_layout)
        
        # 进程选择组
        process_group = QGroupBox("目标选择")
        process_layout = QVBoxLayout()
        
        self.process_tree = QTreeWidget()
        self.process_tree.setHeaderLabels(["应用", "PID", "窗口标题"])
        self.process_tree.setColumnCount(3)
        self.process_tree.setSortingEnabled(True)
        
        process_layout.addWidget(self.process_tree)
        process_group.setLayout(process_layout)
        
        # 控制按钮
        self.start_btn = QPushButton("开始捕获")
        self.stop_btn = QPushButton("停止捕获")
        self.stop_btn.setEnabled(False)
        
        # 添加到控制面板
        control_layout.addWidget(audio_group)
        control_layout.addWidget(process_group)
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.stop_btn)
        control_layout.addStretch()
        
        # 右侧主面板
        main_panel = QWidget()
        main_layout = QVBoxLayout(main_panel)
        
        # 字幕工具栏
        toolbar = QHBoxLayout()
        
        self.clear_btn = QPushButton("清空")
        self.save_btn = QPushButton("保存")
        self.font_btn = QPushButton("字体")
        self.color_btn = QPushButton("颜色")
        
        toolbar.addWidget(self.clear_btn)
        toolbar.addWidget(self.save_btn)
        toolbar.addWidget(self.font_btn)
        toolbar.addWidget(self.color_btn)
        toolbar.addStretch()
        
        # 字幕显示区
        self.subtitle_display = QTextEdit()
        self.subtitle_display.setReadOnly(True)
        
        # 状态栏
        self.status_bar = QLabel("准备就绪")
        
        # 添加到主面板
        main_layout.addLayout(toolbar)
        main_layout.addWidget(self.subtitle_display)
        main_layout.addWidget(self.status_bar)
        
        # 整体布局
        layout.addWidget(control_panel)
        layout.addWidget(main_panel)
        
        # 连接信号槽
        self.connect_signals()
        
        # 应用样式
        self.apply_theme('light')

    def init_menu(self):
        """初始化菜单栏"""
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu("文件")
        
        new_action = QAction("新建会话", self)
        open_action = QAction("打开...", self)
        save_action = QAction("保存", self)
        exit_action = QAction("退出", self)
        
        file_menu.addAction(new_action)
        file_menu.addAction(open_action)
        file_menu.addAction(save_action)
        file_menu.addSeparator()
        file_menu.addAction(exit_action)
        
        # 编辑菜单
        edit_menu = menubar.addMenu("编辑")
        
        copy_action = QAction("复制", self)
        paste_action = QAction("粘贴", self)
        clear_action = QAction("清空", self)
        
        edit_menu.addAction(copy_action)
        edit_menu.addAction(paste_action)
        edit_menu.addSeparator()
        edit_menu.addAction(clear_action)
        
        # 视图菜单
        view_menu = menubar.addMenu("视图")
        
        theme_menu = view_menu.addMenu("主题")
        light_action = QAction("明亮", self)
        dark_action = QAction("暗黑", self)
        
        theme_menu.addAction(light_action)
        theme_menu.addAction(dark_action)
        
        # 工具菜单
        tools_menu = menubar.addMenu("工具")
        
        settings_action = QAction("设置", self)
        update_action = QAction("检查更新", self)
        
        tools_menu.addAction(settings_action)
        tools_menu.addAction(update_action)
        
        # 帮助菜单
        help_menu = menubar.addMenu("帮助")
        
        about_action = QAction("关于", self)
        docs_action = QAction("文档", self)
        
        help_menu.addAction(about_action)
        help_menu.addAction(docs_action)

    def init_tray(self):
        """初始化系统托盘"""
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon('icon.ico'))
        
        tray_menu = QMenu()
        
        show_action = QAction("显示", self)
        hide_action = QAction("隐藏", self)
        exit_action = QAction("退出", self)
        
        tray_menu.addAction(show_action)
        tray_menu.addAction(hide_action)
        tray_menu.addSeparator()
        tray_menu.addAction(exit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    def connect_signals(self):
        """连接所有信号槽"""
        self.start_btn.clicked.connect(self.start_capture)
        self.stop_btn.clicked.connect(self.stop_capture)
        self.clear_btn.clicked.connect(self.clear_subtitles)
        self.save_btn.clicked.connect(self.save_subtitles)
        self.font_btn.clicked.connect(self.change_font)
        self.color_btn.clicked.connect(self.change_color)
        
        # 设备改变时更新
        self.device_combo.currentIndexChanged.connect(self.update_audio_settings)
        self.sample_rate_combo.currentIndexChanged.connect(self.update_audio_settings)
        self.volume_slider.valueChanged.connect(self.update_volume)

    def apply_theme(self, theme):
        """应用主题样式"""
        self.config['theme'] = theme
        
        palette = self.palette()
        
        if theme == 'dark':
            palette.setColor(QPalette.Window, QColor(53, 53, 53))
            palette.setColor(QPalette.WindowText, Qt.white)
            palette.setColor(QPalette.Base, QColor(25, 25, 25))
            palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
            palette.setColor(QPalette.ToolTipBase, Qt.black)
            palette.setColor(QPalette.ToolTipText, Qt.white)
            palette.setColor(QPalette.Text, Qt.white)
            palette.setColor(QPalette.Button, QColor(53, 53, 53))
            palette.setColor(QPalette.ButtonText, Qt.white)
            palette.setColor(QPalette.BrightText, Qt.red)
            palette.setColor(QPalette.Link, QColor(42, 130, 218))
            palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
            palette.setColor(QPalette.HighlightedText, Qt.black)
        else:
            palette.setColor(QPalette.Window, QColor(240, 240, 240))
            palette.setColor(QPalette.WindowText, Qt.black)
            palette.setColor(QPalette.Base, Qt.white)
            palette.setColor(QPalette.AlternateBase, QColor(233, 231, 227))
            palette.setColor(QPalette.ToolTipBase, Qt.white)
            palette.setColor(QPalette.ToolTipText, Qt.black)
            palette.setColor(QPalette.Text, Qt.black)
            palette.setColor(QPalette.Button, QColor(240, 240, 240))
            palette.setColor(QPalette.ButtonText, Qt.black)
            palette.setColor(QPalette.BrightText, Qt.red)
            palette.setColor(QPalette.Link, QColor(0, 0, 255))
            palette.setColor(QPalette.Highlight, QColor(0, 120, 215))
            palette.setColor(QPalette.HighlightedText, Qt.white)
        
        self.setPalette(palette)
        
        # 额外样式
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
            QPushButton {
                padding: 5px;
                min-width: 80px;
            }
            QTextEdit {
                border: 1px solid #ccc;
                border-radius: 3px;
                padding: 5px;
            }
            QTreeWidget {
                border: 1px solid #ccc;
                border-radius: 3px;
            }
        """)

    def load_model(self):
        """加载语音识别模型"""
        try:
            if os.path.exists(self.config['recognition']['model_path']):
                self.model = Model(self.config['recognition']['model_path'])
                self.status_bar.setText("语音模型加载成功")
            else:
                self.status_bar.setText("警告: 未找到语音模型")
        except Exception as e:
            self.status_bar.setText(f"模型加载错误: {str(e)}")

    def update_devices(self):
        """更新音频设备列表"""
        self.device_combo.clear()
        
        for i in range(self.audio.get_device_count()):
            dev = self.audio.get_device_info_by_index(i)
            if dev['maxInputChannels'] > 0:
                self.device_combo.addItem(
                    f"{dev['name']} (Ch: {dev['maxInputChannels']})",
                    userData=dev
                )

    def update_processes(self):
        """更新进程列表"""
        self.process_tree.clear()
        
        # 获取所有窗口
        windows = []
        
        def enum_windows(hwnd, ctx):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    try:
                        proc = psutil.Process(pid)
                        windows.append({
                            'hwnd': hwnd,
                            'pid': pid,
                            'title': title,
                            'name': proc.name(),
                            'exe': proc.exe()
                        })
                    except:
                        pass
            return True
        
        win32gui.EnumWindows(enum_windows, None)
        
        # 按进程名分组
        processes = {}
        for window in windows:
            if window['name'] not in processes:
                processes[window['name']] = []
            processes[window['name']].append(window)
        
        # 添加到树形控件
        for name, wins in processes.items():
            parent = QTreeWidgetItem(self.process_tree)
            parent.setText(0, name)
            parent.setText(1, str(wins[0]['pid']))
            
            for win in wins:
                child = QTreeWidgetItem(parent)
                child.setText(0, win['title'])
                child.setText(1, str(win['pid']))
                child.setText(2, win['title'])
        
        self.process_tree.expandAll()

    def start_capture(self):
        """开始捕获音频"""
        if self.is_recording:
            return
        
        # 获取选择的设备
        device_index = self.device_combo.currentIndex()
        if device_index < 0:
            QMessageBox.warning(self, "警告", "请先选择音频设备")
            return
        
        device = self.device_combo.itemData(device_index)
        sample_rate = int(self.sample_rate_combo.currentText())
        
        try:
            # 初始化识别器
            self.recognizer = KaldiRecognizer(self.model, sample_rate)
            
            # 打开音频流
            self.stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=sample_rate,
                input=True,
                input_device_index=device['index'],
                frames_per_buffer=self.config['audio']['chunk_size'],
                stream_callback=self.audio_callback
            )
            
            self.stream.start_stream()
            self.is_recording = True
            
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            
            self.status_bar.setText(f"正在捕获: {device['name']}")
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法开始捕获: {str(e)}")
            self.status_bar.setText("捕获启动失败")

    def stop_capture(self):
        """停止捕获音频"""
        if not self.is_recording:
            return
        
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
        
        self.is_recording = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_bar.setText("捕获已停止")

    def audio_callback(self, in_data, frame_count, time_info, status):
        """音频回调函数"""
        if self.recognizer.AcceptWaveform(in_data):
            result = json.loads(self.recognizer.Result())
            text = result.get('text', '')
            if text:
                self.update_subtitle(text)
        
        return (in_data, pyaudio.paContinue)

    def update_subtitle(self, text):
        """更新字幕显示"""
        cursor = self.subtitle_display.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text + "\n")
        
        if self.config['ui']['auto_scroll']:
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
                self.status_bar.setText(f"字幕已保存到: {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存失败: {str(e)}")

    def change_font(self):
        """更改字幕字体"""
        font, ok = QFontDialog.getFont()
        if ok:
            self.subtitle_display.setFont(font)
            self.config['font']['family'] = font.family()
            self.config['font']['size'] = font.pointSize()

    def change_color(self):
        """更改字幕颜色"""
        color = QColorDialog.getColor()
        if color.isValid():
            self.subtitle_display.setTextColor(color)

    def update_audio_settings(self):
        """更新音频设置"""
        device_index = self.device_combo.currentIndex()
        if device_index >= 0:
            self.config['audio']['input_device'] = self.device_combo.itemData(device_index)
        
        self.config['audio']['sample_rate'] = int(self.sample_rate_combo.currentText())

    def update_volume(self, value):
        """更新音量设置"""
        self.config['audio']['volume'] = value

    def load_settings(self):
        """加载设置"""
        try:
            if os.path.exists('settings.json'):
                with open('settings.json', 'r', encoding='utf-8') as f:
                    self.config.update(json.load(f))
        except Exception as e:
            print(f"设置加载失败: {str(e)}")

    def save_settings(self):
        """保存设置"""
        try:
            with open('settings.json', 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"设置保存失败: {str(e)}")

    def closeEvent(self, event):
        """关闭事件"""
        self.stop_capture()
        self.save_settings()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # 检查模型目录
    if not os.path.exists('models'):
        os.makedirs('models')
        QMessageBox.information(
            None, '模型目录', 
            '请将语音识别模型放入models文件夹中'
        )
    
    window = UltimateAudioTranscriber()
    window.show()
    sys.exit(app.exec_())