import os
import ast
import sys

def check_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        try:
            tree = ast.parse(f.read(), filename=filepath)
        except SyntaxError as e:
            print(f"CRITICAL SYNTAX ERROR in {filepath}: line {e.lineno}: {e.msg}")
            return
        except Exception as e:
            print(f"Could not parse {filepath}: {e}")
            return

    # Check for undefined names (simplified)
    # This is a basic check and won't catch everything, but it's better than nothing
    # for a quick scan without external deps working well.
    # Actually, let's just look for specific patterns or just rely on syntax checks first.
    # A full undefined name checker in AST is complex.
    # Let's stick to Syntax checking for now as that's the "will it crash immediately" check.
    print(f"Checked {filepath}: OK")

def scan_project(root_dir):
    print(f"Scanning {root_dir} for Syntax Errors...")
    issues = 0
    for root, dirs, files in os.walk(root_dir):
        for file in files:
            if file.endswith('.py'):
                path = os.path.join(root, file)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        ast.parse(f.read(), filename=path)
                except SyntaxError as e:
                    print(f"❌ SYNTAX ERROR: {path}:{e.lineno} - {e.msg}")
                    issues += 1
                except Exception as e:
                    print(f"⚠️ Read Error: {path} - {e}")
    
    if issues == 0:
        print("\n✅ No Syntax Errors found! The code is parseable.")
    else:
        print(f"\n❌ Found {issues} syntax errors.")

if __name__ == "__main__":
    scan_project("src")
