#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import subprocess
import shutil
import platform
from pathlib import Path
import importlib.util
import site

def get_project_root():
    """获取项目根目录"""
    return Path(__file__).parent.absolute()

def check_pyinstaller():
    """检查PyInstaller是否安装并获取其路径"""
    try:
        import PyInstaller
        pyinstaller_path = Path(PyInstaller.__file__).parent
        print(f"PyInstaller路径: {pyinstaller_path}")
        return True
    except ImportError:
        print("PyInstaller未安装，正在安装...")
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'pyinstaller'])
        return True

def collect_project_modules():
    """动态收集项目中的所有Python模块"""
    root_dir = get_project_root()
    modules = []
    exclude_dirs = ['__pycache__', '.git', 'venv', 'env', 'build', 'dist', '.idea', '.vscode']
    exclude_files = [
        'pack.spec', 'build.py', 'dynamic_build.py', 'dynamic_build_fixed.py',
        'main.py', 'debug_train.py', 'pyproject.toml', 'setup.py', 'launcher.py'
    ]

    for root, dirs, files in os.walk(root_dir):
        if any(excl in root for excl in exclude_dirs):
            continue

        for file in files:
            if file.endswith('.py'):
                rel_path = os.path.relpath(os.path.join(root, file), root_dir)
                if file in exclude_files or rel_path in exclude_files:
                    continue

                module_path = rel_path.replace(os.sep, '.').replace('.py', '')
                if module_path.startswith('.'):
                    module_path = module_path[1:]

                if module_path and not module_path.startswith('_'):
                    modules.append(module_path)

    return modules

def create_runtime_hook():
    """创建运行时钩子文件"""
    hook_content = '''# -*- coding: utf-8 -*-
import os
import sys

def setup_qt_environment():
    """设置 Qt 环境变量"""
    if getattr(sys, 'frozen', False):
        # 打包后的环境
        bundle_dir = sys._MEIPASS

        # 添加 PySide6 路径
        pyside6_path = os.path.join(bundle_dir, 'PySide6')
        if os.path.exists(pyside6_path):
            os.environ['PATH'] = pyside6_path + os.pathsep + os.environ.get('PATH', '')

        # 添加 plugins 路径
        plugins_path = os.path.join(bundle_dir, 'PySide6', 'plugins')
        if os.path.exists(plugins_path):
            os.environ['PATH'] = plugins_path + os.pathsep + os.environ.get('PATH', '')

        # 设置 Qt 插件路径
        os.environ['QT_PLUGIN_PATH'] = plugins_path

        # 禁用沙箱（如果使用 WebEngine）
        os.environ['QTWEBENGINE_DISABLE_SANDBOX'] = '1'

        print(f"[Runtime Hook] Bundle dir: {bundle_dir}")
        print(f"[Runtime Hook] PySide6 path exists: {os.path.exists(pyside6_path)}")
        print(f"[Runtime Hook] Plugins path exists: {os.path.exists(plugins_path)}")
        print(f"[Runtime Hook] QT_PLUGIN_PATH: {os.environ.get('QT_PLUGIN_PATH', 'Not set')}")

# 在导入 Qt 之前执行
setup_qt_environment()
'''

    hook_path = Path(get_project_root()) / 'hook_pyside6_runtime.py'
    with open(hook_path, 'w', encoding='utf-8') as f:
        f.write(hook_content)
    print(f"✅ 运行时钩子已创建: {hook_path}")
    return hook_path

def create_qt_conf():
    """创建 qt.conf 文件"""
    qt_conf = '''[Paths]
Prefix = .
Plugins = PySide6/plugins
'''
    qt_conf_path = Path(get_project_root()) / 'qt.conf'
    with open(qt_conf_path, 'w', encoding='utf-8') as f:
        f.write(qt_conf)
    print(f"✅ qt.conf 已创建: {qt_conf_path}")
    return qt_conf_path

def generate_release_spec_content(modules, runtime_hook_path):
    """生成 Release 模式的 spec 文件内容"""
    root_dir = get_project_root()
    project_name = root_dir.name if root_dir.name else 'VisionTrainingApp'

    # 🔴 Release 模式：只包含必要的 hidden imports
    base_hidden_imports = [
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        'PySide6.QtNetwork',
        'PySide6.QtOpenGL',
        'PySide6.QtPrintSupport',
        'PySide6.QtSql',
        'PySide6.QtTest',
        'PySide6.QtXml',
        'PySide6.QtSvg',
        'PySide6.QtUiTools',
        'PySide6.QtQml',
        'PySide6.QtQuick',
        'PySide6.QtQuickControls2',
        'PySide6.QtOpenGLWidgets',
        'shiboken6',
        'cv2',
        'numpy',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
    ]

    all_hidden_imports = list(set(base_hidden_imports + modules))
    hidden_imports_str = ',\n    '.join(f"'{imp}'" for imp in all_hidden_imports)

    spec_template = f'''# -*- mode: python ; coding: utf-8 -*-
# 🔴 Release 模式打包配置

import sys
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# 设置路径
project_dir = r'{root_dir}'
sys.path.insert(0, project_dir)

# 收集PySide6资源文件
pyside6_datas = collect_data_files('PySide6')

# 🔴 关键：手动添加平台插件
import PySide6
pyside6_base_path = Path(PySide6.__file__).parent
plugins_path = pyside6_base_path / 'plugins'

platform_plugins = []
if plugins_path.exists():
    # 添加整个 plugins 目录
    platform_dir = str(plugins_path / 'platforms')
    if os.path.exists(platform_dir):
        platform_plugins.append((platform_dir, 'PySide6/plugins/platforms'))

    # 添加其他必要的插件
    for plugin_dir in ['styles', 'imageformats', 'mediaservice']:
        plugin_path = plugins_path / plugin_dir
        if plugin_path.exists():
            platform_plugins.append((str(plugin_path), f'PySide6/plugins/{plugin_dir}'))

print(f"收集的平台插件: {{platform_plugins}}")

# 收集额外的资源文件
additional_datas = [
    (str(Path(__file__).parent / 'qt.conf'), 'qt.conf'),  # qt.conf 文件
]

# 合并所有数据文件
all_datas = pyside6_datas + platform_plugins + additional_datas

# 🔴 Release 模式：只包含必要的 hidden imports
hiddenimports = [
    {hidden_imports_str},
]

# 🔴 Release 模式：排除更多不必要的模块
excludes = [
    'tkinter',
    'test',
    'distutils',
    'unittest',
    'pdb',
    'idlelib',
    'pydoc',
    'email',
    'http',
    'xml',
    'html',
    'urllib',
    'ctypes',
    'curses',
    'dbm',
    'json',
    'mailbox',
    'multiprocessing',
    'profile',
    'pstats',
    'smtplib',
    'zipfile',
    'tarfile',
    'uu',
    'base64',
    'asyncio',
    'concurrent',
    'multiprocessing',
]

a = Analysis(
    ['launcher.py'],  # 使用 launcher.py 作为入口
    pathex=[project_dir],
    binaries=[],
    datas=all_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=['{runtime_hook_path}'],  # 🔴 添加运行时钩子
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,  # 禁用归档模式，提高性能
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# 查找图标
icon_file = None
if os.path.exists('app.ico'):
    icon_file = 'app.ico'
elif os.path.exists('icon.ico'):
    icon_file = 'icon.ico'

# 🔴 Release 模式配置（不使用UPX）
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='{project_name}',
    debug=False,  # 🔴 关闭调试
    bootloader_ignore_signals=False,
    strip=True,   # 🔴 启用strip，减小文件大小
    upx=False,    # 🔴 禁用UPX压缩
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 🔴 不显示控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
)
'''
    return spec_template

def clean_build():
    """清理构建文件"""
    root_dir = get_project_root()
    dirs_to_clean = ['build', 'dist', '__pycache__']

    for dir_name in dirs_to_clean:
        dir_path = root_dir / dir_name
        if dir_path.exists():
            print(f"清理 {dir_path}...")
            shutil.rmtree(dir_path)

    for path in root_dir.rglob('__pycache__'):
        if path.is_dir():
            print(f"清理 {path}...")
            shutil.rmtree(path)

    for spec_file in root_dir.glob('*.spec'):
        print(f"删除 {spec_file}...")
        spec_file.unlink()

def build_release():
    """构建 Release 版本"""
    print("=" * 60)
    print("🔴 开始 Release 模式打包（不使用UPX）")
    print("=" * 60)
    print(f"Python版本: {sys.version}")
    print(f"系统平台: {platform.system()}")
    print(f"项目目录: {get_project_root()}")
    print("=" * 60)

    # 检查关键依赖
    required_packages = ['PySide6', 'opencv-python', 'numpy']
    for package in required_packages:
        try:
            importlib.import_module(package.replace('-', '_'))
            print(f"✓ {package} 已安装")
        except ImportError:
            print(f"✗ {package} 未安装")
            print("正在安装...")
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', package])

    # 🔴 创建运行时钩子和 qt.conf
    print("\n创建运行配置文件...")
    runtime_hook_path = create_runtime_hook()
    qt_conf_path = create_qt_conf()

    try:
        # 检查 PyInstaller
        if not check_pyinstaller():
            return False

        # 清理
        clean_build()

        # 收集模块
        print("\n收集模块...")
        modules = collect_project_modules()
        print(f"找到 {len(modules)} 个模块")
        if modules:
            print(f"模块示例: {modules[:5]}...")

        # 生成 Release spec 文件
        print("\n生成 Release 配置...")
        spec_content = generate_release_spec_content(modules, str(runtime_hook_path))
        spec_file = 'pack.spec'
        with open(spec_file, 'w', encoding='utf-8') as f:
            f.write(spec_content)
        print(f"spec 文件已生成: {spec_file}")

        # 🔴 Release 模式打包命令（不使用UPX）
        print("\n开始 Release 打包...")
        cmd = [
            sys.executable, '-m', 'PyInstaller',
            spec_file,
            '--clean',
            '--noconfirm',
            '--log-level=WARN',
            '--strip',
            '--noupx',  # 🔴 明确禁用 UPX
        ]

        # 添加额外的隐藏导入
        extra_hidden_imports = [
            'shiboken6',
            'PySide6.QtCore',
            'PySide6.QtGui',
            'PySide6.QtWidgets',
            'PySide6.QtMultimedia',
        ]
        for imp in extra_hidden_imports:
            cmd.extend(['--hidden-import', imp])

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"打包失败: {result.stderr}")
            print(f"标准输出: {result.stdout}")
            return False

        print("\n✅ Release 打包完成！")

        # 显示程序位置
        project_name = get_project_root().name
        exe_dir = Path('dist') / project_name
        exe_path = exe_dir / f"{project_name}.exe"

        if exe_path.exists():
            print(f"程序位置: {exe_path}")
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            print(f"文件大小: {size_mb:.2f} MB")

            # 验证关键文件是否存在
            print("\n验证关键文件...")
            dist_dir = Path('dist') / project_name
            plugin_dir = dist_dir / 'PySide6' / 'plugins' / 'platforms'
            if plugin_dir.exists():
                print(f"✅ 平台插件存在: {plugin_dir}")
            else:
                print(f"⚠️ 平台插件不存在: {plugin_dir}")

            qt_conf_check = dist_dir / 'qt.conf'
            if qt_conf_check.exists():
                print(f"✅ qt.conf 存在: {qt_conf_check}")
            else:
                print(f"⚠️ qt.conf 不存在: {qt_conf_check}")
        else:
            print(f"程序位置: dist/{project_name}/")

        return True

    except Exception as e:
        print(f"打包失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """主函数"""
    success = build_release()

    if not success:
        print("\n❌ Release 打包失败")
        print("\n请检查以下事项：")
        print("1. 确保所有依赖已安装: pip install -r requirements.txt")
        print("2. 检查项目文件是否完整")
        print("3. 查看错误信息并修复")
        print("4. 检查 launcher.py 是否存在")
        print("5. 确保 PySide6 正确安装")
        print("6. 程序不使用 UPX 压缩，所以无需安装 UPX")

    input("\n按 Enter 键退出...")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n打包被用户中断")
    except Exception as e:
        print(f"\n发生错误: {e}")
        import traceback
        traceback.print_exc()
        input("按 Enter 键退出...")