import sys
import csv
import pandas as pd
import numpy as np
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel, QHBoxLayout, QPushButton, QToolTip, QStatusBar, QGridLayout, QDoubleSpinBox, QSizePolicy
from PySide6.QtGui import QColor, QPen, QFont
from PySide6.QtCore import Qt, QPointF, Signal, Slot, QSize, QRect, QPoint

# matplotlib 相关导入
import matplotlib
matplotlib.use('QtAgg')
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import Polygon, Circle
import matplotlib.pyplot as plt
from matplotlib.backend_bases import MouseButton
import io

# 新增导入
from scipy.spatial import KDTree

# 解决中文显示问题
plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans', 'Bitstream Vera Sans', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False  # 用来正常显示负号

class MappingVisualizer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("偏移量图绘制程序")
        self.resize(800, 600)

        # 缩放和偏移参数
        self.design_scale = 60.0  # 设计值缩放
        self.offset_scale = 1.0   # 偏移量缩放
        self.shot_separation = 4  # Shot分离参数
        self.spec_x = 2.5        # X方向规格值
        self.spec_y = 2.5        # Y方向规格值

        # 加载Seq数据
        self.seq_data = {}
        self.load_seq_data()

        # 存储绘图数据
        self.polygons = {}  # 理论多边形 {shot: {seq: point}}
        self.actual_polygons = {}  # 实际多边形 {GLASS_ID_ENDTIME: {shot: {seq: point}}}
        self.offset_data = {}  # 偏移量数据 {GLASS_ID_ENDTIME: {site_name: {param: value}}}
        
        # 均值多边形数据
        self.mean_polygon = {}  # {shot: {seq: point}}

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
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)  # 减小边距
        main_layout.setSpacing(2)  # 减小组件间距
        
        # 绘图区域 - 放在最上方，占据主要空间
        self.canvas = MatplotlibCanvas(self, self.seq_data)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        main_layout.addWidget(self.canvas, 1)  # 设置stretch因子为1，允许扩展
        
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
        
        # X规格值
        params_layout.addWidget(QLabel("X规格值:"), 1, 0)
        self.spec_x_spin = QDoubleSpinBox()
        self.spec_x_spin.setRange(0.0, 10.0)
        self.spec_x_spin.setSingleStep(0.1)
        self.spec_x_spin.setValue(self.spec_x)
        self.spec_x_spin.valueChanged.connect(self.on_param_changed)
        params_layout.addWidget(self.spec_x_spin, 1, 1)
        
        # Y规格值
        params_layout.addWidget(QLabel("Y规格值:"), 1, 2)
        self.spec_y_spin = QDoubleSpinBox()
        self.spec_y_spin.setRange(0.0, 10.0)
        self.spec_y_spin.setSingleStep(0.1)
        self.spec_y_spin.setValue(self.spec_y)
        self.spec_y_spin.valueChanged.connect(self.on_param_changed)
        params_layout.addWidget(self.spec_y_spin, 1, 3)
        
        main_layout.addLayout(params_layout)
        
        # 添加控制按钮 - 放在底部
        control_layout = QHBoxLayout()
        control_layout.setContentsMargins(0, 0, 0, 0)  # 减小边距
        
        self.zoom_in_btn = QPushButton("放大(+)")
        self.zoom_in_btn.clicked.connect(self.on_zoom_in)
        self.zoom_in_btn.setMaximumHeight(30)  # 设置按钮高度
        control_layout.addWidget(self.zoom_in_btn)
        
        self.zoom_out_btn = QPushButton("缩小(-)")
        self.zoom_out_btn.clicked.connect(self.on_zoom_out)
        self.zoom_out_btn.setMaximumHeight(30)  # 设置按钮高度
        control_layout.addWidget(self.zoom_out_btn)
        
        self.reset_view_btn = QPushButton("重置视图(R)")
        self.reset_view_btn.clicked.connect(self.on_reset_view)
        self.reset_view_btn.setMaximumHeight(30)  # 设置按钮高度
        control_layout.addWidget(self.reset_view_btn)
        
        self.grid_btn = QPushButton("显示网格")
        self.grid_btn.setCheckable(True)
        self.grid_btn.setChecked(True)
        self.grid_btn.clicked.connect(self.on_grid_toggled)
        self.grid_btn.setMaximumHeight(30)
        control_layout.addWidget(self.grid_btn)
        
        # 状态标签 - 放在最右侧
        self.status_label = QLabel("等待剪贴板数据...")
        self.status_label.setMaximumHeight(30)  # 设置标签高度
        control_layout.addWidget(self.status_label, 1)  # 允许标签扩展填充剩余空间
        
        main_layout.addLayout(control_layout)
        
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
        self.spec_x = self.spec_x_spin.value()
        self.spec_y = self.spec_y_spin.value()
        
        # 重新处理数据，刷新图表
        if hasattr(self, 'last_df') and self.last_df is not None:
            self.process_data(self.last_df)
        else:
            self.canvas.set_params(self.design_scale, self.offset_scale, self.shot_separation, self.spec_x, self.spec_y)
            self.canvas.draw()
    
    @Slot(bool)
    def on_grid_toggled(self, checked):
        """切换是否显示网格"""
        self.canvas.show_grid = checked
        self.canvas.redraw_plot()

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
        self.polygons = {}  # {shot: {seq: point}}
        self.actual_polygons = {}  # {key: {shot: {seq: point}}}
        self.offset_data = {}  # {GLASS_ID_ENDTIME: {site_name: {param: value}}}
        self.mean_polygon = {}  # {shot: {seq: point}}
        
        # 用于传递给Canvas的数据
        original_coords = {}  # {site_name: (x, y)}
        offset_values = {}    # {glass_key: {site_name: {'POS_X1': x, 'POS_Y1': y}}}
        
        # 第一步：处理理论多边形数据和站点映射
        site_theory_coords = {}  # {site_name: (x, y)}
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
                self.polygons[shot][seq] = (scaled_x, scaled_y)
                
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
        # 收集所有偏移量数据，用于计算均值
        all_offsets = {}  # {site_name: [(offset_x, offset_y), ...]}
        
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
                
                # 收集偏移量数据
                if site_name not in all_offsets:
                    all_offsets[site_name] = []
                all_offsets[site_name].append((offset_x, offset_y))
                
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
                self.actual_polygons[glass_key][shot][seq] = (actual_x, actual_y)
        
        # 第四步：计算均值多边形
        for site_name, offset_list in all_offsets.items():
            if site_name not in self.seq_data:
                continue
                
            shot, seq = self.seq_data[site_name]
            
            # 获取该站点的理论坐标
            if site_name not in site_theory_coords:
                continue
            
            # 计算平均偏移量
            if offset_list:
                avg_offset_x = sum(o[0] for o in offset_list) / len(offset_list)
                avg_offset_y = sum(o[1] for o in offset_list) / len(offset_list)
            else:
                avg_offset_x, avg_offset_y = 0, 0
            
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
            
            # 计算均值坐标 = 理论坐标 + 平均偏移量
            mean_x = scaled_x + avg_offset_x
            mean_y = scaled_y + avg_offset_y
            
            # 保存均值多边形数据
            if shot not in self.mean_polygon:
                self.mean_polygon[shot] = {}
            self.mean_polygon[shot][seq] = (mean_x, mean_y)
        
        # 更新状态并绘制
        theory_count = len(self.polygons)
        actual_count = len(self.actual_polygons)
        status_text = f"已加载数据: {theory_count}个Shot, {actual_count}组数据"
        self.statusBar.showMessage(status_text)
        self.status_label.setText(status_text)
        
        # 设置参数并更新画布
        self.canvas.set_params(self.design_scale, self.offset_scale, self.shot_separation, self.spec_x, self.spec_y)
        # 传递原始坐标和偏移量数据
        self.canvas.set_original_data(original_coords, offset_values)
        self.canvas.update_polygons(self.polygons, self.actual_polygons, self.mean_polygon)

    @Slot()
    def on_zoom_in(self):
        self.canvas.zoom_in()
    
    @Slot()
    def on_zoom_out(self):
        self.canvas.zoom_out()
    
    @Slot()
    def on_reset_view(self):
        self.canvas.reset_view()


class MatplotlibCanvas(FigureCanvas):
    def __init__(self, parent=None, seq_data=None):
        # 创建图形和坐标轴
        self.fig = Figure(figsize=(5, 4), dpi=100)
        self.axes = self.fig.add_subplot(111)
        super().__init__(self.fig)
        
        # 设置父窗口
        self.setParent(parent)
        
        # 绘图数据
        self.theory_polygons = {}  # {shot: {seq: point}}
        self.actual_polygon_sets = {}  # {key: {shot: {seq: point}}}
        self.seq_data = seq_data or {}
        
        # 网格设置
        self.show_grid = True
        self.grid_spacing = 1  # 网格间距
        
        # 缩放和偏移参数
        self.design_scale = 10.0
        self.offset_scale = 1.0
        self.shot_separation = 3
        self.spec_x = 2.5
        self.spec_y = 2.5
        
        # 存储原始坐标和偏移量数据，用于显示提示信息
        self.original_coords = {}  # {site_name: (x, y)}
        self.offset_values = {}    # {glass_key: {site_name: {'POS_X1': x, 'POS_Y1': y}}}
        
        # 绘图元素
        self.theory_lines = []
        self.theory_points = []
        self.actual_lines = []
        self.actual_points = []
        self.mean_lines = []
        self.mean_points = []
        self.highlight_point = None
        
        # 悬停检测用
        self.point_metadata = []  # 初始化point_metadata属性
        self.point_kdtree = None
        
        # 颜色设置
        self.theory_color = '#0047AB'  # 深钴蓝色 (Cobalt Blue)
        self.mean_color = '#7CFC00'    # 草坪绿 (LawnGreen)
        self.actual_color = '#FF4500'  # 橙红色 (OrangeRed)
        
        # 设置图形的初始样式
        self.setup_figure()
        
        # 连接事件处理器
        self.setup_events()
        
        # 鼠标操作相关
        self.hover_info = ""
        self.press_event = None
        self.background = None
        
        # 初始绘制
        self.draw()
    
    def set_params(self, design_scale, offset_scale, shot_separation, spec_x, spec_y):
        """设置缩放和偏移参数"""
        self.design_scale = design_scale
        self.offset_scale = offset_scale
        self.shot_separation = shot_separation
        self.spec_x = spec_x
        self.spec_y = spec_y
    
    def set_original_data(self, original_coords, offset_values):
        """设置原始坐标和偏移量数据，用于显示提示信息"""
        self.original_coords = original_coords
        self.offset_values = offset_values
    
    def setup_figure(self):
        """设置图形的初始样式"""
        # 设置坐标轴属性
        self.axes.set_aspect('equal')  # 等比例显示
        self.axes.tick_params(axis='both', which='major', labelsize=8)
        self.axes.tick_params(axis='both', which='minor', labelsize=6)
        
        # 设置网格
        self.axes.grid(self.show_grid, linestyle=':', color='gray', alpha=0.5)
        
        # 设置紧凑布局
        self.fig.tight_layout(pad=0.1)
    
    def setup_events(self):
        """连接事件处理器"""
        self.mpl_connect('motion_notify_event', self.on_mouse_move)
        self.mpl_connect('button_press_event', self.on_mouse_press)
        self.mpl_connect('button_release_event', self.on_mouse_release)
        self.mpl_connect('scroll_event', self.on_scroll)
        self.mpl_connect('resize_event', self.on_resize_event)
    
    def update_polygons(self, theory_polygons, actual_polygon_sets, mean_polygon):
        """更新多边形数据并重新绘制"""
        self.theory_polygons = theory_polygons
        self.actual_polygon_sets = actual_polygon_sets
        self.mean_polygon = mean_polygon
        self.redraw_plot()
    
    def redraw_plot(self):
        """优化后的重新绘制图表函数"""
        # 清除当前绘图
        self.axes.clear()
        self.theory_lines = []
        self.theory_points = []
        self.actual_lines = []
        self.actual_points = []
        self.mean_lines = []
        self.mean_points = []
        
        # 重新设置网格
        if self.show_grid:
            self.axes.grid(True, linestyle=':', color='gray', alpha=0.5)
            # 设置网格间隔为1
            self.axes.xaxis.set_major_locator(plt.MultipleLocator(1))
            self.axes.yaxis.set_major_locator(plt.MultipleLocator(1))
        else:
            self.axes.grid(False)
        
        # 存储点元数据用于悬停检测
        self.point_metadata = []
        
        # ----- 绘制理论多边形 -----
        for shot, points in self.theory_polygons.items():
            sorted_points = [points[seq] for seq in sorted(points.keys())]
            if len(sorted_points) >= 2:
                # 线条点（闭合多边形）
                closed_points = sorted_points + [sorted_points[0]]
                xs = [p[0] for p in closed_points]
                ys = [p[1] for p in closed_points]
                
                # 绘制理论多边形线条
                line, = self.axes.plot(xs, ys, color=self.theory_color, linewidth=2)
                self.theory_lines.append(line)
                
                # 绘制理论多边形顶点
                x_points = [p[0] for p in sorted_points]
                y_points = [p[1] for p in sorted_points]
                scatter = self.axes.scatter(x_points, y_points, 
                                           color=self.theory_color,
                                           edgecolors='black', 
                                           s=15, zorder=5)
                self.theory_points.append(scatter)
                
                # 收集理论点元数据
                for seq, point in points.items():
                    self.point_metadata.append((point[0], point[1], True, shot, seq, None))
                
                # 绘制规格值虚线框
                for seq, point in points.items():
                    x, y = point
                    # 根据偏移量缩放计算规格值框
                    spec_x_scaled = self.spec_x / self.offset_scale
                    spec_y_scaled = self.spec_y / self.offset_scale
                    
                    # 绘制虚线框
                    rect = plt.Rectangle(
                        (x - spec_x_scaled, y - spec_y_scaled),
                        2 * spec_x_scaled,
                        2 * spec_y_scaled,
                        linestyle='--',
                        linewidth=1,
                        edgecolor='#006400',  # 深绿色，更易于区分
                        facecolor='none',
                        alpha=0.7
                    )
                    self.axes.add_patch(rect)
        
        # ----- 绘制均值多边形 -----
        for shot, points in self.mean_polygon.items():
            sorted_points = [points[seq] for seq in sorted(points.keys())]
            if len(sorted_points) >= 2:
                # 线条点（闭合多边形）
                closed_points = sorted_points + [sorted_points[0]]
                xs = [p[0] for p in closed_points]
                ys = [p[1] for p in closed_points]
                
                # 绘制均值多边形线条
                line, = self.axes.plot(xs, ys, color=self.mean_color, linewidth=2)
                self.mean_lines.append(line)
                
                # 绘制均值多边形顶点
                x_points = [p[0] for p in sorted_points]
                y_points = [p[1] for p in sorted_points]
                scatter = self.axes.scatter(x_points, y_points, 
                                          color=self.mean_color,
                                          edgecolors='black', 
                                          s=15, zorder=5)
                self.mean_points.append(scatter)
                
                # 收集均值点元数据
                for seq, point in points.items():
                    self.point_metadata.append((point[0], point[1], False, shot, seq, "均值"))
        
        # ----- 绘制实际多边形（只绘制点，不绘制线） -----
        # 收集所有实际点
        actual_points = []
        
        for glass_key, polygon_set in self.actual_polygon_sets.items():
            for shot, points in polygon_set.items():
                for seq, point in points.items():
                    actual_points.append(point)
                    # 收集实际点元数据
                    self.point_metadata.append((point[0], point[1], False, shot, seq, glass_key))
        
        # 一次性绘制所有实际点
        if actual_points:
            x_actual = [p[0] for p in actual_points]
            y_actual = [p[1] for p in actual_points]
            scatter = self.axes.scatter(x_actual, y_actual, 
                                       color=self.actual_color,
                                       edgecolors='black', 
                                       s=5, alpha=0.5, zorder=3)
            self.actual_points.append(scatter)
        
        # 自动调整视图以显示所有多边形
        self.auto_scale()
        
        # 初始化KDTree用于快速搜索
        self.build_spatial_index()
        
        # 添加图例
        self.axes.plot([], [], color=self.theory_color, linewidth=1, label='设计坐标')
        self.axes.plot([], [], color=self.mean_color, linewidth=1, label='实做均值')
        self.axes.scatter([], [], color=self.actual_color, s=5, alpha=0.5, label='实做点')
        self.axes.legend(loc='upper right')
        
        # 重新绘制
        self.draw()
    
    def auto_scale(self):
        """自动调整坐标轴以适应所有多边形"""
        if not self.theory_polygons and not self.actual_polygon_sets:
            return
        
        all_points = []
        
        # 收集所有点
        for shot, points in self.theory_polygons.items():
            for seq, point in points.items():
                all_points.append(point)
        
        for key, polygon_set in self.actual_polygon_sets.items():
            for shot, points in polygon_set.items():
                for seq, point in points.items():
                    all_points.append(point)
        
        if not all_points:
            return
        
        # 计算边界
        x_coords = [p[0] for p in all_points]
        y_coords = [p[1] for p in all_points]
        
        x_min, x_max = min(x_coords), max(x_coords)
        y_min, y_max = min(y_coords), max(y_coords)
        
        # 添加边距 - 减小padding以减少留白
        padding = 0.1
        x_range = x_max - x_min
        y_range = y_max - y_min
        
        # 确保有最小范围
        if x_range < 1e-10:
            x_range = 1
        if y_range < 1e-10:
            y_range = 1
        
        x_padding = padding * x_range
        y_padding = padding * y_range
        
        # 设置坐标轴范围
        self.axes.set_xlim(x_min - x_padding, x_max + x_padding)
        self.axes.set_ylim(y_min - y_padding, y_max + y_padding)
    
    def zoom_in(self):
        """放大视图"""
        self.zoom(1.2)
    
    def zoom_out(self):
        """缩小视图"""
        self.zoom(1/1.2)
    
    def zoom(self, factor):
        """缩放视图"""
        # 获取当前视图范围
        x_min, x_max = self.axes.get_xlim()
        y_min, y_max = self.axes.get_ylim()
        
        # 计算中心点
        x_center = (x_min + x_max) / 2
        y_center = (y_min + y_max) / 2
        
        # 计算新范围
        x_range = (x_max - x_min) / factor
        y_range = (y_max - y_min) / factor
        
        # 设置新范围
        self.axes.set_xlim(x_center - x_range/2, x_center + x_range/2)
        self.axes.set_ylim(y_center - y_range/2, y_center + y_range/2)
        
        # 重新绘制
        self.draw_idle()
    
    def reset_view(self):
        """重置视图"""
        self.auto_scale()
        self.draw_idle()
    
    def on_mouse_move(self, event):
        """鼠标移动事件"""
        if not event.inaxes:
            return
        
        if self.press_event and (event.button == MouseButton.LEFT or event.button == MouseButton.MIDDLE):
            # 处理拖动 - 平移视图
            dx = event.xdata - self.press_event.xdata
            dy = event.ydata - self.press_event.ydata
            
            # 获取当前视图范围
            x_min, x_max = self.axes.get_xlim()
            y_min, y_max = self.axes.get_ylim()
            
            # 计算新范围
            self.axes.set_xlim(x_min - dx, x_max - dx)
            self.axes.set_ylim(y_min - dy, y_max - dy)
            
            # 更新按下位置
            self.press_event.xdata = event.xdata
            self.press_event.ydata = event.ydata
            
            # 直接重绘，不使用blitting技术（更可靠）
            self.draw_idle()
        else:
            # 检查鼠标悬停
            self.check_hover(event)
    
    def on_mouse_press(self, event):
        """鼠标按下事件"""
        if not event.inaxes:
            return
        
        if event.button == MouseButton.LEFT or event.button == MouseButton.MIDDLE:
            # 开始拖动
            self.press_event = event
    
    def on_mouse_release(self, event):
        """鼠标释放事件"""
        self.press_event = None
    
    def on_scroll(self, event):
        """鼠标滚轮事件 - 用于缩放"""
        if not event.inaxes:
            return
        
        # 获取当前视图范围
        x_min, x_max = self.axes.get_xlim()
        y_min, y_max = self.axes.get_ylim()
        
        # 计算缩放因子
        factor = 1.1 if event.button == 'up' else 1/1.1
        
        # 计算鼠标位置的比例
        x_range = x_max - x_min
        y_range = y_max - y_min
        x_rel = (event.xdata - x_min) / x_range
        y_rel = (event.ydata - y_min) / y_range
        
        # 计算新范围
        new_x_range = x_range / factor
        new_y_range = y_range / factor
        
        # 设置新范围，保持鼠标位置不变
        self.axes.set_xlim(
            event.xdata - x_rel * new_x_range,
            event.xdata + (1 - x_rel) * new_x_range
        )
        self.axes.set_ylim(
            event.ydata - y_rel * new_y_range,
            event.ydata + (1 - y_rel) * new_y_range
        )
        
        # 重新绘制
        self.draw_idle()
    
    def on_resize_event(self, event):
        """窗口大小改变时清除背景缓存"""
        # 不再需要background
        # 更新布局
        self.fig.tight_layout(pad=0.1)
        self.draw_idle()
    
    def build_spatial_index(self):
        """构建空间索引用于快速点查找"""
        try:
            from scipy.spatial import KDTree
            import numpy as np
            
            # 构建所有点的坐标数组
            if not hasattr(self, 'point_metadata') or not self.point_metadata:
                return
                
            coordinates = np.array([(x, y) for x, y, *_ in self.point_metadata])
            
            # 创建KDTree
            self.point_kdtree = KDTree(coordinates)
        except ImportError:
            print("警告: 未安装scipy，将使用暴力搜索")
            self.point_kdtree = None

    def check_hover(self, event):
        """优化后的鼠标悬停检测"""
        if not event.inaxes:
            # 鼠标不在坐标轴内
            return
            
        # 删除之前的高亮点
        if self.highlight_point:
            self.highlight_point.remove()
            self.highlight_point = None
        
        # 获取鼠标位置
        mx, my = event.xdata, event.ydata
        closest_point = None
        hover_info = None
        site_name = None
        
        # 设置距离阈值
        distance_threshold = 0.5
        
        # 确保point_metadata已初始化
        if not hasattr(self, 'point_metadata') or not self.point_metadata:
            # 如果没有点数据，直接返回
            self.draw_idle()
            return
        
        try:
            # 找到最近的点
            if hasattr(self, 'point_kdtree') and self.point_kdtree is not None:
                # 使用KDTree快速搜索
                distances, indices = self.point_kdtree.query([mx, my], k=1)
                
                if distances < distance_threshold:
                    # 找到了足够近的点
                    index = indices
                    x, y, is_theory, shot, seq, glass_key = self.point_metadata[index]
                    closest_point = (x, y)
                else:
                    # 没有找到足够近的点
                    self.draw_idle()
                    QToolTip.hideText()
                    return
            else:
                # 暴力搜索（备用方案）
                min_dist = float('inf')
                index = -1
                for i, (x, y, is_theory, shot, seq, glass_key) in enumerate(self.point_metadata):
                    dist = np.sqrt((x - mx)**2 + (y - my)**2)
                    if dist < min_dist and dist < distance_threshold:
                        min_dist = dist
                        closest_point = (x, y)
                        index = i
                
                if index == -1:
                    # 没有找到足够近的点
                    self.draw_idle()
                    QToolTip.hideText()
                    return
                
                # 获取最近点的信息
                x, y, is_theory, shot, seq, glass_key = self.point_metadata[index]
            
            # 找到站点名称
            for site_name_tmp, (shot_tmp, seq_tmp) in self.seq_data.items():
                if shot_tmp == shot and seq_tmp == seq:
                    site_name = site_name_tmp
                    break
            
            # 构建悬停信息
            if is_theory:
                hover_info = f"理论点 - Shot: {shot}\nSite: {site_name}\n"
                # 查找原始坐标
                if site_name in self.original_coords:
                    orig_x, orig_y = self.original_coords[site_name]
                    hover_info += f"原始坐标: ({orig_x}, {orig_y})"
            elif glass_key == "均值":
                hover_info = f"均值点 - Shot: {shot}\nSite: {site_name}"
            else:
                # 为实际点构建悬停信息
                hover_info = f"实做点 - Shot: {shot}\nSite: {site_name}\nGlass: {glass_key}\n"
                # 查找偏移量
                if glass_key in self.offset_values and site_name in self.offset_values[glass_key]:
                    offsets = self.offset_values[glass_key][site_name]
                    x_offset = offsets.get('POS_X1', 0)
                    y_offset = offsets.get('POS_Y1', 0)
                    hover_info += f"偏移量: X={x_offset}, Y={y_offset}"
            
            # 如果找到了点，显示高亮和工具提示
            if closest_point and hover_info:
                # 绘制高亮点
                self.highlight_point = self.axes.scatter(
                    closest_point[0], 
                    closest_point[1], 
                    color='red', 
                    edgecolors='black', 
                    s=100, 
                    alpha=0.5,
                    zorder=10
                )
                
                # 显示工具提示 - 修正Y坐标，将event.y改为figure高度减去event.y
                fig_height = self.figure.bbox.height
                corrected_y = fig_height - event.y  # 修正Y坐标
                QToolTip.showText(
                    self.mapToGlobal(QPoint(event.x, event.y)),
                    hover_info
                )
                
                # 更新绘图
                self.draw_idle()
            else:
                QToolTip.hideText()
                self.draw_idle()
                
        except Exception as e:
            print(f"悬停检测时出错: {e}")
            self.draw_idle()
            return

    def on_resize(self, event):
        """窗口大小改变事件"""
        self.fig.tight_layout(pad=0.1)
        self.draw()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # 设置应用样式
    app.setStyle("Fusion")
    
    # 设置工具提示样式
    QToolTip.setFont(QFont('Sans Serif', 10))
    
    window = MappingVisualizer()
    window.show()
    sys.exit(app.exec()) 