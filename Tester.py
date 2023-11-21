# import sys
# from PyQt5.QtWidgets import QApplication, QMainWindow, QTableView, QVBoxLayout, QWidget, QLineEdit, QHBoxLayout
# from PyQt5.QtCore import Qt, QAbstractTableModel, QVariant

# class MyWindow(QMainWindow):
#     def __init__(self):
#         super().__init__()

#         self.initUI()

#     def initUI(self):
#         self.setWindowTitle("Table View and Line Edits Example")
#         self.setGeometry(100, 100, 600, 400)

#         self.table_view = QTableView()
#         self.table_view.setSelectionBehavior(QTableView.SelectRows)
#         self.table_view.clicked.connect(self.on_table_view_clicked)

#         self.model = TableModel()  # Custom model to handle data
#         self.table_view.setModel(self.model)

#         self.line_edits = [QLineEdit() for _ in range(self.model.columnCount())]
#         for index, line_edit in enumerate(self.line_edits):
#             line_edit.textChanged.connect(lambda text, col=index: self.on_line_edit_changed(text, col))

#         central_widget = QWidget()
#         layout = QVBoxLayout()
#         layout.addWidget(self.table_view)

#         line_edits_layout = QHBoxLayout()
#         for line_edit in self.line_edits:
#             line_edits_layout.addWidget(line_edit)
#         layout.addLayout(line_edits_layout)

#         central_widget.setLayout(layout)
#         self.setCentralWidget(central_widget)

#     def on_table_view_clicked(self, index):
#         row = index.row()
#         for col in range(self.model.columnCount()):
#             data = self.model.data(self.model.index(row, col), Qt.DisplayRole)
#             self.line_edits[col].setText(str(data))

#     def on_line_edit_changed(self, text, col):
#         current_index = self.table_view.selectionModel().currentIndex()
#         if current_index.isValid():
#             row = current_index.row()
#             index = self.model.index(row, col)
#             self.model.setData(index, text, Qt.EditRole)  # Update the model data

# # Custom TableModel for demonstration purposes
# class TableModel(QAbstractTableModel):
#     def __init__(self, parent=None):
#         super(TableModel, self).__init__(parent)
#         self.dataList = [
#             [1, 2, 3],
#             [4, 5, 6],
#             [7, 8, 9],
#             [10, 11, 12]
#         ]

#     def rowCount(self, index=None):
#         return len(self.dataList)

#     def columnCount(self, index=None):
#         if self.dataList:
#             return len(self.dataList[0])
#         return 0

#     def data(self, index, role):
#         if role == Qt.DisplayRole:
#             return self.dataList[index.row()][index.column()]
#         return QVariant()

#     def setData(self, index, value, role):
#         if role == Qt.EditRole:
#             row = index.row()
#             col = index.column()
#             self.dataList[row][col] = value
#             self.dataChanged.emit(index, index)
#             return True
#         return False

# if __name__ == '__main__':
#     app = QApplication(sys.argv)
#     window = MyWindow()
#     window.show()
#     sys.exit(app.exec_())


import sys
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QLabel
import math
import ast

class MathCalculator(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle('Mathematical Expression Calculator')

        self.input_line = QLineEdit()
        self.result_label = QLabel()

        sqrt_button = QPushButton('√')
        sqrt_button.clicked.connect(self.add_sqrt_symbol)

        calculate_button = QPushButton('Calculate')
        calculate_button.clicked.connect(self.calculate_result)

        input_layout = QHBoxLayout()
        input_layout.addWidget(self.input_line)
        input_layout.addWidget(sqrt_button)

        result_layout = QVBoxLayout()
        result_layout.addLayout(input_layout)
        result_layout.addWidget(calculate_button)
        result_layout.addWidget(self.result_label)

        self.setLayout(result_layout)
        self.show()

    def add_sqrt_symbol(self):
        current_text = self.input_line.text()
        self.input_line.setText(current_text + '√')

    def calculate_result(self):
        expression = self.input_line.text().replace('√', 'math.sqrt')

        try:
            parsed_expression = ast.parse(expression, mode='eval')
            evaluated = eval(compile(parsed_expression, '<string>', 'eval'), {"math": math})
            self.result_label.setText(f'Result: {evaluated}')
        except Exception as e:
            self.result_label.setText(f'Error: {e}')

if __name__ == '__main__':
    app = QApplication(sys.argv)
    calc = MathCalculator()
    sys.exit(app.exec_())
