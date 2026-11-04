
import os
import ast
import sys
from collections import defaultdict

# Add project root to path
sys.path.append(os.getcwd())

def get_class_methods(file_path):
    """Extract all class methods from a python file."""
    methods = defaultdict(set)
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read())
            
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_name = node.name
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        methods[class_name].add(item.name)
    except Exception as e:
        print(f"Error parsing {file_path}: {e}")
    return methods

def audit_ui_files(ui_dir, feature_methods):
    """Scan UI files for calls to feature classes."""
    issues = []
    
    for root, _, files in os.walk(ui_dir):
        for file in files:
            if not file.endswith(".py"):
                continue
                
            file_path = os.path.join(root, file)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    tree = ast.parse(content)
                
                # Map variable names to class names for this file
                var_map = {}
                
                # 1. Scan for assignments in __init__
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and node.name == '__init__':
                        for stmt in node.body:
                            if isinstance(stmt, ast.Assign):
                                for target in stmt.targets:
                                    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == 'self':
                                        # self.var = Class()
                                        if isinstance(stmt.value, ast.Call) and isinstance(stmt.value.func, ast.Name):
                                            var_name = target.attr
                                            class_name = stmt.value.func.id
                                            var_map[var_name] = class_name
                
                # 2. Scan for method calls
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        if isinstance(node.func, ast.Attribute):
                            # Check for self.something.method()
                            if isinstance(node.func.value, ast.Attribute):
                                if isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == 'self':
                                    # Found self.obj.method()
                                    obj_name = node.func.value.attr
                                    method_name = node.func.attr
                                    
                                    # Resolve class name
                                    class_name = var_map.get(obj_name)
                                    
                                    # Fallback to heuristic if not found in __init__
                                    if not class_name:
                                        class_name = map_variable_to_class(obj_name)
                                    
                                    if class_name and class_name in feature_methods:
                                        if method_name not in feature_methods[class_name]:
                                            issues.append({
                                                'file': file,
                                                'line': node.lineno,
                                                'object': obj_name,
                                                'class': class_name,
                                                'method': method_name,
                                                'error': 'Method not found in backend class'
                                            })
            except Exception as e:
                print(f"Error auditing {file}: {e}")
                
    return issues

def map_variable_to_class(var_name):
    """Heuristic mapping of variable names to class names."""
    mapping = {
        'tagger': 'AIAssetTagger',
        'ai_tagger': 'AIAssetTagger',
        'automation': 'AutomationEngine',
        'automation_engine': 'AutomationEngine',
        'diagnostics': 'DiagnosticEngine',
        'diagnostic_engine': 'DiagnosticEngine',
        'quality': 'QualityAnalyzer',
        'quality_analyzer': 'QualityAnalyzer',
        'batch_processor': 'SmartBatchProcessor',
        'processor': 'SmartBatchProcessor', # Ambiguous, but often this
        'vcs': 'VersionControl',
        'version_control': 'VersionControl',
        'perf_analyzer': 'PerformanceAnalyzer',
        'performance': 'PerformanceAnalyzer',
        'post_processor': 'PostProcessor',
        'processor': 'PostProcessor', # Updated heuristic
        'renderer': 'RenderEngine',
        'render_engine': 'RenderEngine'
    }
    return mapping.get(var_name)

def main():
    print("Starting Codebase Audit...")
    
    # 1. Map Backend Features
    scan_dirs = [
        os.path.join(os.getcwd(), 'src', 'features'),
        os.path.join(os.getcwd(), 'src', 'processing'),
        os.path.join(os.getcwd(), 'src', 'core')
    ]
    
    feature_methods = {}
    
    for feature_dir in scan_dirs:
        if not os.path.exists(feature_dir):
            continue
            
        print(f"Scanning {feature_dir}...")
        for root, _, files in os.walk(feature_dir):
            for file in files:
                if file.endswith(".py"):
                    path = os.path.join(root, file)
                    methods = get_class_methods(path)
                    feature_methods.update(methods)
    
    print(f"Found {len(feature_methods)} feature classes.")
    for cls, methods in feature_methods.items():
        print(f"  - {cls}: {len(methods)} methods")

    # 2. Audit UI Files
    ui_dir = os.path.join(os.getcwd(), 'src', 'ui')
    print(f"\nScanning UI in {ui_dir}...")
    issues = audit_ui_files(ui_dir, feature_methods)
    
    # 3. Report
    report_lines = []
    report_lines.append("="*50)
    report_lines.append("AUDIT REPORT")
    report_lines.append("="*50)
    
    if not issues:
        report_lines.append("No broken connections found based on heuristics.")
    else:
        for issue in issues:
            report_lines.append(f"[MISSING] {issue['file']}:{issue['line']} -> {issue['object']}.{issue['method']}() not found in {issue['class']}")
            
    with open('audit_report.txt', 'w', encoding='utf-8') as f:
        f.write("\n".join(report_lines))
    
    print("Audit complete. Report saved to audit_report.txt")

if __name__ == "__main__":
    main()
