import sys
import csv
import pandas as pd
import numpy as np
import io
from PySide6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel, 
                             QHBoxLayout, QPushButton, QGridLayout, QDoubleSpinBox, QStatusBar,
                             QSizePolicy)
from PySide6.QtCore import Qt, Signal, Slot, QSize
from PySide6.QtGui import QFont

from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar


class MatplotlibCanvas(FigureCanvas):
    """Matplotlib画布类，用于在Qt界面中嵌入matplotlib图表"""
    
    def __init__(self, parent=None, width=8, height=6, dpi=100):
        # 创建Figure对象
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        
        # 添加子图
        self.axes = self.fig.add_subplot(111)
        self.axes.grid(True, linestyle='--', alpha=0.7)
        
        # 初始化FigureCanvas
        super(MatplotlibCanvas, self).__init__(self.fig)
        self.setParent(parent)
        
        # 设置FigureCanvas的尺寸策略
        FigureCanvas.setSizePolicy(self,
                                  QSizePolicy.Expanding,
                                  QSizePolicy.Expanding)
        FigureCanvas.updateGeometry(self)
        
        # 数据存储
        self.theory_polygons = {}  # {shot: [(x1,y1), (x2,y2), ...]}
        self.actual_polygons = {}  # {glass_key: {shot: [(x1,y1), (x2,y2), ...]}}
        
        # 原始数据和偏移量数据
        self.original_coords = {}  # {site_name: (x, y)}
        self.offset_values = {}    # {glass_key: {site_name: {'POS_X1': x, 'POS_Y1': y}}}
        self.seq_data = {}  # {site_name: (shot, seq)}
        
        # 绘图参数
        self.design_scale = 10.0
        self.offset_scale = 1.0
        self.shot_separation = 3
        
        # 颜色设置
        self.theory_color = 'blue'
        self.actual_colors = ['red', 'green', 'yellow', 'magenta', 'cyan', 'orange', 'purple', 'olive']
        
        # 连接事件
        self.fig.canvas.mpl_connect('pick_event', self.on_pick)
        self.annotation = self.axes.annotate("", 
                                           xy=(0, 0), xytext=(20, 20),
                                           textcoords="offset points",
                                           bbox=dict(boxstyle="round", fc="w"),
                                           arrowprops=dict(arrowstyle="->"))
        self.annotation.set_visible(False)
    
    def set_params(self, design_scale, offset_scale, shot_separation):
        """设置缩放和偏移参数"""
        self.design_scale = design_scale
        self.offset_scale = offset_scale
        self.shot_separation = shot_separation
    
    def set_seq_data(self, seq_data):
        """设置seq_data映射"""
        self.seq_data = seq_data
    
    def set_original_data(self, original_coords, offset_values):
        """设置原始坐标和偏移量数据"""
        self.original_coords = original_coords
        self.offset_values = offset_values
    
    def update_polygons(self, theory_polygons, actual_polygons):
        """更新多边形数据并重绘图表"""
        # 清空现有数据
        self.theory_polygons = {}
        self.actual_polygons = {}
        
        # 转换理论多边形数据格式
        for shot, points in theory_polygons.items():
            points_list = []
            sorted_seqs = sorted(points.keys())
            for seq in sorted_seqs:
                if seq in points:
                    point = points[seq]
                    points_list.append((point.x(), point.y()))
            if points_list:
                # 首尾相连
                points_list.append(points_list[0])
                self.theory_polygons[shot] = points_list
        
        # 转换实际多边形数据格式
        for glass_key, polygon_set in actual_polygons.items():
            self.actual_polygons[glass_key] = {}
            for shot, points in polygon_set.items():
                points_list = []
                sorted_seqs = sorted(points.keys())
                for seq in sorted_seqs:
                    if seq in points:
                        point = points[seq]
                        points_list.append((point.x(), point.y()))
                if points_list:
                    # 首尾相连
                    points_list.append(points_list[0])
                    self.actual_polygons[glass_key][shot] = points_list
        
        self.plot_data()
    
    def plot_data(self):
        """绘制所有多边形数据"""
        # 清空当前图表
        self.axes.clear()
        
        # 设置坐标轴
        self.axes.set_xlabel('X')
        self.axes.set_ylabel('Y')
        self.axes.grid(True, linestyle='--', alpha=0.7)
        
        # 用于跟踪数据范围
        min_x, max_x = float('inf'), float('-inf')
        min_y, max_y = float('inf'), float('-inf')
        
        # 绘制理论多边形
        for shot, points in self.theory_polygons.items():
            x_coords, y_coords = zip(*points)
            min_x = min(min_x, min(x_coords))
            max_x = max(max_x, max(x_coords))
            min_y = min(min_y, min(y_coords))
            max_y = max(max_y, max(y_coords))
            
            # 绘制线条
            line, = self.axes.plot(x_coords, y_coords, 
                                 color=self.theory_color, 
                                 linestyle='-', 
                                 marker='o',
                                 label=f'Shot {shot} (理论)',
                                 picker=5)  # 启用拾取事件
            
            # 存储数据到线条对象中，用于拾取事件
            line.shot = shot
            line.is_theory = True
            line.glass_key = None
        
        # 绘制实际多边形
        for i, (glass_key, polygon_set) in enumerate(self.actual_polygons.items()):
            color = self.actual_colors[i % len(self.actual_colors)]
            for shot, points in polygon_set.items():
                x_coords, y_coords = zip(*points)
                min_x = min(min_x, min(x_coords))
                max_x = max(max_x, max(x_coords))
                min_y = min(min_y, min(y_coords))
                max_y = max(max_y, max(y_coords))
                
                # 绘制线条
                line, = self.axes.plot(x_coords, y_coords, 
                                     color=color, 
                                     linestyle='-', 
                                     marker='o',
                                     label=f'Shot {shot} (Glass: {glass_key})',
                                     picker=5)  # 启用拾取事件
                
                # 存储数据到线条对象中，用于拾取事件
                line.shot = shot
                line.is_theory = False
                line.glass_key = glass_key
        
        # 设置合适的坐标范围，确保所有数据都可见
        if min_x != float('inf') and max_x != float('-inf') and min_y != float('inf') and max_y != float('-inf'):
            padding = 0.1  # 添加10%的边距
            x_range = max_x - min_x
            y_range = max_y - min_y
            self.axes.set_xlim(min_x - padding * x_range, max_x + padding * x_range)
            self.axes.set_ylim(min_y - padding * y_range, max_y + padding * y_range)
        
        # 添加图例
        self.axes.legend(loc='upper right')
        
        # 更新图表
        self.fig.tight_layout()
        self.draw()
    
    def on_pick(self, event):
        """处理拾取事件 - 当用户点击图表上的点时显示信息"""
        line = event.artist
        ind = event.ind[0]  # 获取点击的点的索引
        
        # 获取点的坐标
        xdata = line.get_xdata()
        ydata = line.get_ydata()
        x, y = xdata[ind], ydata[ind]
        
        # 准备显示的信息
        if line.is_theory:
            # 理论点
            shot = line.shot
            info = f"理论点 - Shot: {shot}\n"
            
            # 寻找对应的原始坐标
            for site_name, (shot_val, seq_val) in self.seq_data.items():
                if shot_val == shot:
                    if site_name in self.original_coords:
                        orig_x, orig_y = self.original_coords[site_name]
                        info += f"原始坐标: ({orig_x}, {orig_y})"
                        break
        else:
            # 实际点
            shot = line.shot
            glass_key = line.glass_key
            info = f"实际点 - Shot: {shot}\nGlass: {glass_key}\n"
            
            # 寻找对应的偏移量
            for site_name, (shot_val, seq_val) in self.seq_data.items():
                if shot_val == shot:
                    if glass_key in self.offset_values and site_name in self.offset_values[glass_key]:
                        offsets = self.offset_values[glass_key][site_name]
                        x_offset = offsets.get('POS_X1', 0)
                        y_offset = offsets.get('POS_Y1', 0)
                        info += f"偏移量: X={x_offset}, Y={y_offset}"
                        break
        
        # 显示标注
        self.annotation.xy = (x, y)
        self.annotation.set_text(info)
        self.annotation.set_visible(True)
        self.draw_idle()  # 重绘画布


class MappingMatplotlibVisualizer(QMainWindow):
    """基于Matplotlib的偏移量图绘制程序主窗口"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("偏移量图绘制程序 (Matplotlib版本)")
        self.resize(1000, 800)
        
        # 缩放和偏移参数
        self.design_scale = 60.0  # 设计值缩放
        self.offset_scale = 1.0   # 偏移量缩放
        self.shot_separation = 4  # Shot分离参数
        
        # 加载Seq数据
        self.seq_data = {}
        self.load_seq_data()
        
        # 存储绘图数据
        self.polygons = {}  # 理论多边形 {shot: {seq: QPointF}}
        self.actual_polygons = {}  # 实际多边形 {GLASS_ID_ENDTIME: {shot: {seq: QPointF}}}
        self.offset_data = {}  # 偏移量数据 {GLASS_ID_ENDTIME: {site_name: {param: value}}}
        
        # 创建UI
        self.setup_ui()
        
        # 监听剪贴板
        self.clipboard = QApplication.clipboard()
        self.clipboard.dataChanged.connect(self.on_clipboard_changed)
    
    def load_seq_data(self):
        """加载seq.csv文件，构建Site到(Shot, Seq)的映射"""
        try:
            with open('seq.csv', 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    site = int(row['Site'])
                    shot = int(row['Shot'])
                    seq = int(row['Seq'])
                    self.seq_data[site] = (shot, seq)
            print(f"已加载{len(self.seq_data)}个Site映射")
        except Exception as e:
            print(f"加载seq.csv文件时出错: {e}")
    
    def setup_ui(self):
        """设置用户界面"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(2)
        
        # 创建Matplotlib画布
        self.canvas = MatplotlibCanvas(central_widget)
        main_layout.addWidget(self.canvas, 1)  # 设置stretch因子为1，允许扩展
        
        # 添加Matplotlib导航工具栏
        self.toolbar = NavigationToolbar(self.canvas, self)
        main_layout.addWidget(self.toolbar)
        
        # 添加参数控制区域
        params_layout = QGridLayout()
        params_layout.setContentsMargins(0, 0, 0, 0)
        
        # 设计值缩放
        params_layout.addWidget(QLabel("设计值缩放:"), 0, 0)
        self.design_scale_spin = QDoubleSpinBox()
        self.design_scale_spin.setRange(0.1, 100.0)
        self.design_scale_spin.setSingleStep(0.5)
        self.design_scale_spin.setValue(self.design_scale)
        self.design_scale_spin.valueChanged.connect(self.on_param_changed)
        params_layout.addWidget(self.design_scale_spin, 0, 1)
        
        # 偏移量缩放
        params_layout.addWidget(QLabel("偏移量缩放:"), 0, 2)
        self.offset_scale_spin = QDoubleSpinBox()
        self.offset_scale_spin.setRange(0.1, 100.0)
        self.offset_scale_spin.setSingleStep(0.5)
        self.offset_scale_spin.setValue(self.offset_scale)
        self.offset_scale_spin.valueChanged.connect(self.on_param_changed)
        params_layout.addWidget(self.offset_scale_spin, 0, 3)
        
        # Shot分离参数
        params_layout.addWidget(QLabel("Shot分离:"), 0, 4)
        self.shot_separation_spin = QDoubleSpinBox()
        self.shot_separation_spin.setRange(0, 50)
        self.shot_separation_spin.setSingleStep(1)
        self.shot_separation_spin.setValue(self.shot_separation)
        self.shot_separation_spin.valueChanged.connect(self.on_param_changed)
        params_layout.addWidget(self.shot_separation_spin, 0, 5)
        
        main_layout.addLayout(params_layout)
        
        # 添加状态栏
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("就绪")
    
    @Slot()
    def on_param_changed(self):
        """参数变化时更新绘图"""
        self.design_scale = self.design_scale_spin.value()
        self.offset_scale = self.offset_scale_spin.value()
        self.shot_separation = self.shot_separation_spin.value()
        
        # 重新处理数据，刷新图表
        if hasattr(self, 'last_df') and self.last_df is not None:
            self.process_data(self.last_df)
        else:
            self.canvas.set_params(self.design_scale, self.offset_scale, self.shot_separation)
            self.canvas.draw()
    
    @Slot()
    def on_clipboard_changed(self):
        """剪贴板内容变化时处理"""
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()
        
        if mime_data.hasText():
            text = clipboard.text()
            try:
                # 尝试将剪贴板文本解析为DataFrame
                df = pd.read_csv(io.StringIO(text), sep=',|\\t', engine='python')
                self.last_df = df  # 保存最后一次处理的数据
                self.process_data(df)
            except Exception as e:
                self.statusBar.showMessage(f"处理剪贴板数据出错: {e}")
    
    def process_data(self, df):
        """处理剪贴板中的数据"""
        required_columns = ['GLASS_ID', 'GLASS_END_TIME', 'SITE_NAME', 'X', 'Y']
        
        # 检查是否包含必要的列
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            self.statusBar.showMessage(f"剪贴板数据缺少必要的列: {', '.join(missing_columns)}")
            return
        
        # 检查是否包含PARAM_NAME和PARAM_VALUE列
        if 'PARAM_NAME' not in df.columns or 'PARAM_VALUE' not in df.columns:
            self.statusBar.showMessage("剪贴板数据缺少PARAM_NAME或PARAM_VALUE列")
            return
        
        # 清空现有数据
        self.polygons = {}  # {shot: {seq: QPointF}}
        self.actual_polygons = {}  # {glass_key: {shot: {seq: QPointF}}}
        self.offset_data = {}  # {glass_key: {site_name: {param: value}}}
        
        # 用于传递给Canvas的数据
        original_coords = {}  # {site_name: (x, y)}
        offset_values = {}    # {glass_key: {site_name: {'POS_X1': x, 'POS_Y1': y}}}
        
        # 第一步：处理理论多边形数据和站点映射
        site_theory_coords = {}  # {site_name: (x, y)}
        from PySide6.QtCore import QPointF
        
        for _, row in df.iterrows():
            try:
                site_name = int(row['SITE_NAME'])
                x, y = float(row['X']), float(row['Y'])
                
                # 记录每个站点的理论坐标
                site_theory_coords[site_name] = (x, y)
                original_coords[site_name] = (x, y)  # 保存原始坐标
                
                # 检查site_name是否在seq_data中
                if site_name not in self.seq_data:
                    print(f"警告: Site {site_name} 在seq.csv中未找到")
                    continue
                    
                shot, seq = self.seq_data[site_name]
                
                # 应用设计值缩放和Shot分离
                # 除以设计值缩放系数*1000后取整
                scaled_x = int(x / (self.design_scale * 1000))
                scaled_y = int(y / (self.design_scale * 1000))
                
                # 应用Shot分离
                if shot == 2:  # 右下
                    scaled_x += self.shot_separation
                    scaled_y -= self.shot_separation
                elif shot == 3:  # 左下
                    scaled_x -= self.shot_separation
                    scaled_y -= self.shot_separation
                elif shot == 4:  # 左上
                    scaled_x -= self.shot_separation
                    scaled_y += self.shot_separation
                elif shot == 1:  # 右上
                    scaled_x += self.shot_separation
                    scaled_y += self.shot_separation
                
                # 构建理论多边形数据
                if shot not in self.polygons:
                    self.polygons[shot] = {}
                self.polygons[shot][seq] = QPointF(scaled_x, scaled_y)
                
            except (ValueError, KeyError) as e:
                print(f"处理理论坐标时出错: {e}")
                continue
        
        # 第二步：处理偏移量数据
        for _, row in df.iterrows():
            try:
                if pd.isna(row.get('PARAM_NAME')) or pd.isna(row.get('PARAM_VALUE')):
                    continue
                    
                glass_id = str(row['GLASS_ID'])
                end_time = str(row['GLASS_END_TIME'])
                site_name = int(row['SITE_NAME'])
                param_name = str(row['PARAM_NAME'])
                param_value = float(row['PARAM_VALUE'])
                
                key = f"{glass_id}_{end_time}"
                
                # 仅处理POS_X1和POS_Y1参数
                if param_name not in ['POS_X1', 'POS_Y1']:
                    continue
                
                # 存储偏移量数据
                if key not in self.offset_data:
                    self.offset_data[key] = {}
                if site_name not in self.offset_data[key]:
                    self.offset_data[key][site_name] = {}
                
                self.offset_data[key][site_name][param_name] = param_value
                
                # 保存偏移量数据给Canvas
                if key not in offset_values:
                    offset_values[key] = {}
                if site_name not in offset_values[key]:
                    offset_values[key][site_name] = {}
                offset_values[key][site_name][param_name] = param_value
                
            except (ValueError, KeyError) as e:
                print(f"处理偏移量数据时出错: {e}")
                continue
        
        # 第三步：根据偏移量构建实际多边形
        for glass_key, offsets in self.offset_data.items():
            self.actual_polygons[glass_key] = {}
            
            for site_name, params in offsets.items():
                if site_name not in self.seq_data:
                    continue
                    
                shot, seq = self.seq_data[site_name]
                
                # 获取该站点的理论坐标
                if site_name not in site_theory_coords:
                    continue
                
                # 获取X和Y偏移量，如果没有则默认为0
                offset_x = params.get('POS_X1', 0) / self.offset_scale
                offset_y = params.get('POS_Y1', 0) / self.offset_scale
                
                # 应用设计值缩放和Shot分离
                x, y = site_theory_coords[site_name]
                scaled_x = int(x / (self.design_scale * 1000))
                scaled_y = int(y / (self.design_scale * 1000))
                
                # 应用Shot分离
                if shot == 2:  # 右下
                    scaled_x += self.shot_separation
                    scaled_y -= self.shot_separation
                elif shot == 3:  # 左下
                    scaled_x -= self.shot_separation
                    scaled_y -= self.shot_separation
                elif shot == 4:  # 左上
                    scaled_x -= self.shot_separation
                    scaled_y += self.shot_separation
                elif shot == 1:  # 右上
                    scaled_x += self.shot_separation
                    scaled_y += self.shot_separation
                
                # 计算实际坐标 = 理论坐标 + 偏移量
                actual_x = scaled_x + offset_x
                actual_y = scaled_y + offset_y
                
                # 保存实际多边形数据
                if shot not in self.actual_polygons[glass_key]:
                    self.actual_polygons[glass_key][shot] = {}
                self.actual_polygons[glass_key][shot][seq] = QPointF(actual_x, actual_y)
        
        # 更新状态
        theory_count = len(self.polygons)
        actual_count = len(self.actual_polygons)
        status_text = f"已加载数据: {theory_count}个Shot, {actual_count}组数据"
        self.statusBar.showMessage(status_text)
        
        # 设置参数并更新画布
        self.canvas.set_params(self.design_scale, self.offset_scale, self.shot_separation)
        self.canvas.set_seq_data(self.seq_data)
        self.canvas.set_original_data(original_coords, offset_values)
        self.canvas.update_polygons(self.polygons, self.actual_polygons)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    window = MappingMatplotlibVisualizer()
    window.show()
    
    sys.exit(app.exec()) 