import ast
import traceback

file_path = r"d:\money printer\MoneyPrinterTurbo-Extended\webui\Main.py"

try:
    with open(file_path, 'r', encoding='utf-8') as f:
        source = f.read()
    ast.parse(source)
    print("AST Parse Successful! No syntax or indentation errors found.")
except IndentationError as e:
    print(f"IndentationError: {e.msg}")
    print(f"Line: {e.lineno}, Offset: {e.offset}")
    print(f"Text: {e.text}")
except SyntaxError as e:
    print(f"SyntaxError: {e.msg}")
    print(f"Line: {e.lineno}, Offset: {e.offset}")
    print(f"Text: {e.text}")
except Exception as e:
    print(f"Other Error: {str(e)}")
    traceback.print_exc()
