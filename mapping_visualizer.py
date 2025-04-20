import sys
import csv
import pandas as pd
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel, QHBoxLayout, QPushButton, QToolTip, QStatusBar, QGridLayout, QDoubleSpinBox
from PySide6.QtGui import QPainter, QColor, QPen, QPolygonF, QFont, QFontMetrics
from PySide6.QtCore import Qt, QPointF, Signal, Slot, QSize, QRectF, QPoint
import io


class MappingVisualizer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("偏移量图绘制程序")
        self.resize(800, 600)

        # 缩放和偏移参数
        self.design_scale = 60.0  # 设计值缩放
        self.offset_scale = 1.0   # 偏移量缩放
        self.shot_separation = 4  # Shot分离参数

        # 加载Seq数据
        self.seq_data = {}
        self.load_seq_data()

        # 存储绘图数据
        self.polygons = {}  # 理论多边形 {shot: {seq: point}}
        self.actual_polygons = {}  # 实际多边形 {GLASS_ID_ENDTIME: {shot: {seq: point}}}
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
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)  # 减小边距
        main_layout.setSpacing(2)  # 减小组件间距
        
        # 绘图区域 - 放在最上方，占据主要空间
        self.canvas = Canvas(self)
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
        
        # 重新处理数据，刷新图表
        if hasattr(self, 'last_df') and self.last_df is not None:
            self.process_data(self.last_df)
        else:
            self.canvas.set_params(self.design_scale, self.offset_scale, self.shot_separation)
            self.canvas.update()
    
    @Slot(bool)
    def on_grid_toggled(self, checked):
        """切换是否显示网格"""
        self.canvas.show_grid = checked
        self.canvas.update()

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
        
        # 更新状态并绘制
        theory_count = len(self.polygons)
        actual_count = len(self.actual_polygons)
        status_text = f"已加载数据: {theory_count}个Shot, {actual_count}组数据"
        self.statusBar.showMessage(status_text)
        self.status_label.setText(status_text)
        
        # 设置参数并更新画布
        self.canvas.set_params(self.design_scale, self.offset_scale, self.shot_separation)
        # 传递原始坐标和偏移量数据
        self.canvas.seq_data = self.seq_data  # 传递seq_data以便鼠标悬停时查找
        self.canvas.set_original_data(original_coords, offset_values)
        self.canvas.update_polygons(self.polygons, self.actual_polygons)
        self.canvas.update()

    @Slot()
    def on_zoom_in(self):
        self.canvas.zoom_in()
    
    @Slot()
    def on_zoom_out(self):
        self.canvas.zoom_out()
    
    @Slot()
    def on_reset_view(self):
        self.canvas.reset_view()


class Canvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(QSize(600, 400))
        self.setMouseTracking(True)  # 启用鼠标追踪
        
        # 绘图数据
        self.theory_polygons = {}  # {shot: {seq: point}}
        self.actual_polygon_sets = {}  # {key: {shot: {seq: point}}}
        
        # 绘图设置
        self.scale_factor = 1.0
        self.offset_x = 0
        self.offset_y = 0
        self.zoom_factor = 1.2
        
        # 网格设置
        self.show_grid = True
        self.grid_spacing = 1  # 网格间距
        
        # 缩放和偏移参数
        self.design_scale = 10.0
        self.offset_scale = 1.0
        self.shot_separation = 3
        
        # 鼠标相关
        self.panning = False
        self.last_mouse_pos = QPoint(0, 0)
        self.hover_point = None
        self.hover_info = ""
        
        # 颜色设置
        self.theory_color = QColor(0, 0, 255, 200)  # 蓝色半透明
        self.actual_colors = [
            QColor(255, 0, 0, 200),     # 红色
            QColor(0, 255, 0, 200),     # 绿色
            QColor(255, 255, 0, 200),   # 黄色 
            QColor(255, 0, 255, 200),   # 洋红
            QColor(0, 255, 255, 200),   # 青色
            QColor(255, 165, 0, 200),   # 橙色
            QColor(128, 0, 128, 200),   # 紫色
            QColor(0, 128, 0, 200)      # 深绿色
        ]
        
        # 点信息映射：用于在鼠标悬停时显示
        # {(x,y): {'type': 'theory/actual', 'shot': shot, 'seq': seq, 'key': key}}
        self.point_info_map = {}
        
        # 存储原始坐标和偏移量数据，用于显示提示信息
        self.original_coords = {}  # {site_name: (x, y)}
        self.offset_values = {}    # {glass_key: {site_name: {'POS_X1': x, 'POS_Y1': y}}}
    
    def set_params(self, design_scale, offset_scale, shot_separation):
        """设置缩放和偏移参数"""
        self.design_scale = design_scale
        self.offset_scale = offset_scale
        self.shot_separation = shot_separation
    
    def update_polygons(self, theory_polygons, actual_polygon_sets):
        """更新多边形数据"""
        self.theory_polygons = theory_polygons
        self.actual_polygon_sets = actual_polygon_sets
        
        # 更新点信息映射
        self.update_point_info_map()
        
        # 自动计算缩放和偏移以适应视图
        self.auto_scale()
    
    def set_original_data(self, original_coords, offset_values):
        """设置原始坐标和偏移量数据，用于显示提示信息"""
        self.original_coords = original_coords
        self.offset_values = offset_values
    
    def update_point_info_map(self):
        """更新点信息映射，用于鼠标悬停显示"""
        self.point_info_map = {}
        
        # 理论点
        for shot, points in self.theory_polygons.items():
            for seq, point in points.items():
                key = (point.x(), point.y())
                self.point_info_map[key] = {
                    'type': 'theory',
                    'shot': shot,
                    'seq': seq
                }
        
        # 实际点
        for glass_key, polygon_set in self.actual_polygon_sets.items():
            for shot, points in polygon_set.items():
                for seq, point in points.items():
                    key = (point.x(), point.y())
                    if key not in self.point_info_map:
                        self.point_info_map[key] = []
                    
                    info = {
                        'type': 'actual',
                        'shot': shot,
                        'seq': seq,
                        'glass_key': glass_key
                    }
                    
                    if isinstance(self.point_info_map[key], list):
                        self.point_info_map[key].append(info)
                    else:
                        # 如果之前存储的不是列表（可能是理论点），将其转换为列表
                        existing = self.point_info_map[key]
                        self.point_info_map[key] = [existing, info]
    
    def auto_scale(self):
        """自动计算缩放和偏移"""
        # 如果没有数据，不进行缩放
        if not self.theory_polygons and not self.actual_polygon_sets:
            return
        
        # 查找所有点的范围
        min_x, max_x = float('inf'), float('-inf')
        min_y, max_y = float('inf'), float('-inf')
        
        # 检查理论多边形
        for shot, points in self.theory_polygons.items():
            for seq, point in points.items():
                min_x = min(min_x, point.x())
                max_x = max(max_x, point.x())
                min_y = min(min_y, point.y())
                max_y = max(max_y, point.y())
        
        # 检查实际多边形
        for key, polygon_set in self.actual_polygon_sets.items():
            for shot, points in polygon_set.items():
                for seq, point in points.items():
                    min_x = min(min_x, point.x())
                    max_x = max(max_x, point.x())
                    min_y = min(min_y, point.y())
                    max_y = max(max_y, point.y())
        
        # 确保有数据
        if min_x == float('inf') or max_x == float('-inf') or min_y == float('inf') or max_y == float('-inf'):
            return
        
        # 计算缩放因子
        width = max_x - min_x
        height = max_y - min_y
        
        if width <= 0 or height <= 0:
            return
        
        # 考虑边距
        margin = 50
        view_width = self.width() - 2 * margin
        view_height = self.height() - 2 * margin
        
        scale_x = view_width / width
        scale_y = view_height / height
        self.scale_factor = min(scale_x, scale_y)
        
        # 计算偏移量，使图形居中
        self.offset_x = margin - min_x * self.scale_factor + (view_width - width * self.scale_factor) / 2
        self.offset_y = margin - min_y * self.scale_factor + (view_height - height * self.scale_factor) / 2
        
        self.update()
    
    def zoom_in(self):
        """放大视图"""
        self.scale_factor *= self.zoom_factor
        self.update()
    
    def zoom_out(self):
        """缩小视图"""
        self.scale_factor /= self.zoom_factor
        self.update()
    
    def reset_view(self):
        """重置视图"""
        self.auto_scale()
    
    def mousePressEvent(self, event):
        """鼠标按下事件"""
        if event.button() == Qt.MiddleButton or event.button() == Qt.LeftButton:
            self.panning = True
            self.last_mouse_pos = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
    
    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        if event.button() == Qt.MiddleButton or event.button() == Qt.LeftButton:
            self.panning = False
            self.setCursor(Qt.ArrowCursor)
    
    def mouseMoveEvent(self, event):
        """鼠标移动事件"""
        if self.panning:
            # 平移视图
            delta = event.position().toPoint() - self.last_mouse_pos
            self.offset_x += delta.x()
            self.offset_y += delta.y()
            self.last_mouse_pos = event.position().toPoint()
            self.update()
        else:
            # 鼠标悬停显示点信息
            self.check_hover(event.position().toPoint())
    
    def check_hover(self, mouse_pos):
        """检查鼠标是否悬停在点上"""
        self.hover_point = None
        self.hover_info = ""
        
        # 检查所有点
        for key, info in self.point_info_map.items():
            x, y = key
            # 将数据坐标转换为屏幕坐标
            screen_x = x * self.scale_factor + self.offset_x
            screen_y = y * self.scale_factor + self.offset_y
            
            # 检查鼠标是否在点的附近
            if abs(mouse_pos.x() - screen_x) < 10 and abs(mouse_pos.y() - screen_y) < 10:
                self.hover_point = QPointF(screen_x, screen_y)
                
                # 设置悬停信息
                if isinstance(info, list):
                    # 处理多个信息的情况
                    for item in info:
                        if item['type'] == 'theory':
                            # 显示理论点的原始坐标
                            shot, seq = item['shot'], item['seq']
                            self.hover_info = f"理论点 - Shot: {shot}\n"
                            # 找到对应的原始坐标
                            for site_name, (orig_x, orig_y) in self.original_coords.items():
                                if self.seq_data.get(site_name) == (shot, seq):
                                    self.hover_info += f"原始坐标: ({orig_x}, {orig_y})"
                                    break
                        else:
                            # 显示实际点的偏移量
                            glass_key = item['glass_key']
                            shot, seq = item['shot'], item['seq']
                            self.hover_info += f"实际点 - Shot: {shot}\nGlass: {glass_key}\n"
                            # 找到对应的偏移量
                            for site_name, offsets in self.offset_values.get(glass_key, {}).items():
                                if self.seq_data.get(site_name) == (shot, seq):
                                    x_offset = offsets.get('POS_X1', 0)
                                    y_offset = offsets.get('POS_Y1', 0)
                                    self.hover_info += f"偏移量: X={x_offset}, Y={y_offset}"
                                    break
                else:
                    # 单个信息
                    if info['type'] == 'theory':
                        # 显示理论点的原始坐标
                        shot, seq = info['shot'], info['seq']
                        self.hover_info = f"理论点 - Shot: {shot}\n"
                        # 找到对应的原始坐标
                        for site_name, (orig_x, orig_y) in self.original_coords.items():
                            if self.seq_data.get(site_name) == (shot, seq):
                                self.hover_info += f"原始坐标: ({orig_x}, {orig_y})"
                                break
                    else:
                        # 显示实际点的偏移量
                        glass_key = info['glass_key']
                        shot, seq = info['shot'], info['seq']
                        self.hover_info = f"实际点 - Shot: {shot}\nGlass: {glass_key}\n"
                        # 找到对应的偏移量
                        for site_name, offsets in self.offset_values.get(glass_key, {}).items():
                            if self.seq_data.get(site_name) == (shot, seq):
                                x_offset = offsets.get('POS_X1', 0)
                                y_offset = offsets.get('POS_Y1', 0)
                                self.hover_info += f"偏移量: X={x_offset}, Y={y_offset}"
                                break
                
                # 显示工具提示
                QToolTip.showText(self.mapToGlobal(mouse_pos), self.hover_info)
                self.update()
                return
        
        # 如果没有找到点，隐藏工具提示
        QToolTip.hideText()
        self.update()
    
    def wheelEvent(self, event):
        """鼠标滚轮事件 - 用于缩放"""
        delta = event.angleDelta().y()
        
        # 获取鼠标位置
        mouse_pos = event.position().toPoint()
        
        # 计算鼠标在数据坐标系中的位置
        mouse_x = (mouse_pos.x() - self.offset_x) / self.scale_factor
        mouse_y = (mouse_pos.y() - self.offset_y) / self.scale_factor
        
        # 根据滚轮方向缩放
        if delta > 0:
            self.scale_factor *= self.zoom_factor
        else:
            self.scale_factor /= self.zoom_factor
        
        # 调整偏移以保持鼠标下的点不变
        self.offset_x = mouse_pos.x() - mouse_x * self.scale_factor
        self.offset_y = mouse_pos.y() - mouse_y * self.scale_factor
        
        self.update()
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.auto_scale()
    
    def paintEvent(self, event):
        if not self.theory_polygons and not self.actual_polygon_sets:
            return
            
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 保存当前的变换矩阵
        painter.save()
        
        # 应用Y轴翻转，使Y轴正向朝上
        painter.translate(0, self.height())
        painter.scale(1, -1)
        
        # 绘制理论多边形
        for shot, points in self.theory_polygons.items():
            self.draw_polygon(painter, points, self.theory_color)
        
        # 绘制实际多边形
        for i, (key, polygon_set) in enumerate(self.actual_polygon_sets.items()):
            color = self.actual_colors[i % len(self.actual_colors)]
            for shot, points in polygon_set.items():
                self.draw_polygon(painter, points, color)
        
        # 如果有悬停点，绘制高亮
        if self.hover_point:
            painter.setPen(QPen(Qt.black, 3))
            painter.setBrush(Qt.red)
            flipped_y = self.height() - self.hover_point.y()
            painter.drawEllipse(QPointF(self.hover_point.x(), flipped_y), 5, 5)
        
        # 恢复变换矩阵
        painter.restore()
        
        # 绘制网格 - 在最上层绘制网格
        if self.show_grid:
            self.draw_grid(painter)
    
    def draw_grid(self, painter):
        """绘制网格"""
        # 设置网格线颜色和样式
        painter.setPen(QPen(QColor(200, 200, 200, 100), 1, Qt.DotLine))
        
        # 计算网格范围
        view_width = self.width()
        view_height = self.height()
        
        # 计算数据坐标系统中的网格范围
        min_x = (0 - self.offset_x) / self.scale_factor
        max_x = (view_width - self.offset_x) / self.scale_factor
        min_y = (0 - self.offset_y) / self.scale_factor
        max_y = (view_height - self.offset_y) / self.scale_factor
        
        # 计算网格线开始和结束的位置
        grid_spacing = self.grid_spacing  # 数据坐标系统中的网格间距
        
        # 计算网格起始点，确保它们是网格间距的整数倍
        start_x = int(min_x / grid_spacing) * grid_spacing
        start_y = int(min_y / grid_spacing) * grid_spacing
        
        # 垂直网格线
        x = start_x
        while x <= max_x:
            screen_x = x * self.scale_factor + self.offset_x
            painter.drawLine(QPointF(screen_x, 0), QPointF(screen_x, view_height))
            x += grid_spacing
        
        # 水平网格线
        y = start_y
        while y <= max_y:
            screen_y = y * self.scale_factor + self.offset_y
            painter.drawLine(QPointF(0, screen_y), QPointF(view_width, screen_y))
            y += grid_spacing
    
    def draw_polygon(self, painter, points_dict, color):
        """绘制一个多边形"""
        if not points_dict:
            return
            
        # 按序号排序点
        sorted_points = []
        seqs = sorted(points_dict.keys())
        for seq in seqs:
            if seq in points_dict:
                sorted_points.append(points_dict[seq])
        
        # 如果有点，确保首尾相连
        if sorted_points and len(sorted_points) >= 2:
            sorted_points.append(sorted_points[0])
        else:
            return
            
        # 创建多边形并应用缩放和偏移（注意Y坐标是在painter中翻转的）
        polygon = QPolygonF()
        for point in sorted_points:
            scaled_x = point.x() * self.scale_factor + self.offset_x
            scaled_y = point.y() * self.scale_factor + self.offset_y
            polygon.append(QPointF(scaled_x, scaled_y))
        
        # 设置画笔
        pen = QPen(color, 2)
        painter.setPen(pen)
        
        # 绘制多边形
        painter.drawPolyline(polygon)
        
        # 绘制顶点，但不显示序号
        for i, seq in enumerate(seqs):
            if seq not in points_dict:
                continue
                
            point = points_dict[seq]
            x = point.x() * self.scale_factor + self.offset_x
            y = point.y() * self.scale_factor + self.offset_y
            
            # 绘制点
            painter.setBrush(color)
            painter.setPen(QPen(Qt.black, 1))
            painter.drawEllipse(QPointF(x, y), 3, 3)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # 设置应用样式
    app.setStyle("Fusion")
    
    # 设置工具提示样式
    QToolTip.setFont(QFont('Sans Serif', 10))
    
    window = MappingVisualizer()
    window.show()
    sys.exit(app.exec()) 