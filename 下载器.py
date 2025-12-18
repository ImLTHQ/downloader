"""
高级文件下载器

一个功能强大的Python下载工具，支持断点续传、智能重试、实时进度显示。

使用方法：python 下载器.py
"""

import os
import sys
import time
import requests
from pathlib import Path
from urllib.parse import urlparse
import urllib3

def get_download_path():
    """
    获取系统默认下载目录
    
    该函数会自动检测当前用户的下载文件夹，如果不存在则创建。
    主要用于设置默认的文件保存路径。
    
    Returns:
        Path: 系统下载目录的Path对象
    """
    download_path = Path(os.environ['USERPROFILE']) / 'Downloads'
    download_path.mkdir(exist_ok=True)
    return download_path

def get_filename_from_url(url):
    """
    从URL中解析并提取文件名
    
    智能解析URL路径，提取最后的文件名部分，并自动移除查询参数。
    如果无法提取到有效文件名，则使用默认名称。
    
    Args:
        url (str): 完整的下载链接地址
        
    Returns:
        str: 清理后的文件名，不包含查询参数
    """
    parsed_url = urlparse(url)
    filename = os.path.basename(parsed_url.path)
    if not filename:
        filename = 'download_file'
    filename = filename.split('?')[0]
    return filename

def format_size(size):
    """
    字节大小单位转换器
    
    将字节数转换为易读的存储单位格式（B、KB、MB、GB、TB），
    自动选择最合适的单位并保留两位小数。
    
    Args:
        size (int): 需要格式化的字节数
        
    Returns:
        str: 格式化后的大小字符串，例如 "1.23 MB"
    """
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    unit_idx = 0
    while size >= 1024 and unit_idx < len(units)-1:
        size /= 1024
        unit_idx += 1
    return f"{size:.2f} {units[unit_idx]}"

def update_progress(downloaded, total, speed):
    """
    实时下载进度显示器
    
    在控制台显示当前下载进度，包括百分比、已下载/总大小和实时速度。
    使用回车符覆盖当前行，实现动态更新效果。
    
    Args:
        downloaded (int): 已下载的字节数
        total (int): 文件总大小（字节）
        speed (int): 当前下载速度（字节/秒）
    """
    if total == 0:
        percent = 100
    else:
        percent = downloaded / total * 100

    # 格式化速率（字节/秒 → KB/s/MB/s）
    speed_str = format_size(speed) + '/s'
    
    downloaded_str = format_size(downloaded)
    total_str = format_size(total)
    
    # 输出简洁的进度信息（覆盖当前行）
    sys.stdout.write(f'\r{percent:.1f}% ({downloaded_str}/{total_str}) {speed_str}')
    sys.stdout.flush()

def check_file_integrity(file_path, expected_size):
    """
    文件完整性验证器
    
    通过检查文件大小和内容头部来验证下载文件的完整性。
    确保文件大小匹配且不是空文件，防止下载损坏的文件。
    
    Args:
        file_path (Path): 待验证文件的路径
        expected_size (int): 文件应有的总大小（字节）
        
    Returns:
        bool: True表示文件完整，False表示文件损坏或不存在
    """
    if not os.path.exists(file_path):
        return False
    actual_size = os.path.getsize(file_path)
    if actual_size == expected_size:
        with open(file_path, 'rb') as f:
            header = f.read(1024)
            if len(header) == 0:
                return False
        return True
    return False





def download_with_auto_resume(url, output_path=None, retry_interval=0):
    """
    智能断点续传下载引擎
    
    这是下载器的核心函数，实现了完整的下载流程管理。
    采用七步下载策略：信息获取→参数初始化→重试循环→请求构建→
    流式下载→完整性验证→结果返回。支持多种异常处理和用户交互。
    
    支持的特性：
    • 智能断点续传：自动检测已有文件，从中断位置继续
    • 无限重试机制：网络异常时自动重试，直到下载完成
    • 实时速度监控：动态显示下载进度和当前速度
    • SSL证书处理：自动忽略SSL验证，解决HTTPS下载问题
    
    Args:
        url (str): 目标文件的下载链接地址
        output_path (str, optional): 自定义下载目录路径，默认使用系统下载目录
        retry_interval (int): 网络异常时的重试等待时间（秒），默认0秒
        
    Returns:
        bool: 下载成功返回True，失败或用户中断返回False
        
    Note:
        - 支持Ctrl+C中断下载，进度会自动保存
        - 损坏文件会自动删除并重新下载
        - 所有HTTPS请求都会跳过SSL证书验证
    """
    # 默认屏蔽SSL警告
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    # 使用自定义下载目录或默认下载目录
    if output_path:
        download_dir = Path(output_path)
        download_dir.mkdir(exist_ok=True)
        filename = get_filename_from_url(url)
        file_path = download_dir / filename
    else:
        download_dir = get_download_path()
        filename = get_filename_from_url(url)
        file_path = download_dir / filename
    
    proxies = None

# 第一步：获取文件总大小和服务器信息
    try:
        head_response = requests.head(url, proxies=proxies, timeout=10, verify=False, allow_redirects=True)
        head_response.raise_for_status()
        file_size = int(head_response.headers.get('Content-Length', 0))
        if file_size == 0:
            print('无法获取文件大小，下载失败')
            return False
    except Exception as e:
        print(f'获取文件信息失败')
        return False

# 第二步：初始化下载参数
    resume_pos = 0
    attempt_count = 0
    success = False

    print(f'开始下载：{filename}（总大小：{format_size(file_size)}）')

    # 第三步：无限重试直到下载完成或用户中断
    while not success:
        attempt_count += 1
        
        # 检查现有文件进度并确定续传位置
        if os.path.exists(file_path):
            current_size = os.path.getsize(file_path)
            if current_size >= file_size:
                if check_file_integrity(file_path, file_size):
                    print(f'\n文件已完整！保存至：{file_path}')
                    success = True
                    break
                else:
                    # 文件损坏，重新下载
                    os.remove(file_path)
                    resume_pos = 0
                    print('检测到文件损坏，重新开始下载')
            else:
                resume_pos = current_size
        else:
            resume_pos = 0

        # 跳过已完成的情况
        if resume_pos >= file_size:
            success = True
            break

        print(f'\n第{attempt_count}次尝试')
        try:
            # 单线程下载模式
            # 构建请求头（断点续传）
            headers = {'Range': f'bytes={resume_pos}-'}
            
            # 创建会话并配置重试机制和代理支持
            session = requests.Session()
            adapter = requests.adapters.HTTPAdapter(max_retries=5)
            session.mount('http://', adapter)
            session.mount('https://', adapter)

            # 第四步：执行下载请求
            response = session.get(
                url,
                headers=headers,
                proxies=proxies,
                stream=True,
                timeout=10,  # 10秒连接/读取超时
                verify=False,
                allow_redirects=True
            )
            response.raise_for_status()

            # 第五步：流式写入文件并实时计算速率
            mode = 'ab' if resume_pos > 0 else 'wb'
            with open(file_path, mode) as f:
                downloaded_in_this_attempt = 0
                start_time = time.time()
                last_check_time = start_time
                last_downloaded = resume_pos

                # 逐块下载并写入文件
                for chunk in response.iter_content(chunk_size=4096):
                    if chunk:
                        f.write(chunk)
                        resume_pos += len(chunk)
                        downloaded_in_this_attempt += len(chunk)
                        
                        # 每秒计算一次下载速率
                        current_time = time.time()
                        if current_time - last_check_time >= 1:
                            # 计算1秒内下载的字节数
                            speed = int((resume_pos - last_downloaded) / (current_time - last_check_time))
                            update_progress(resume_pos, file_size, speed)
                            last_check_time = current_time
                            last_downloaded = resume_pos

            # 第六步：验证下载完整性
            if check_file_integrity(file_path, file_size):
                success = True
            break

        except requests.exceptions.RequestException as e:
            # 网络请求异常处理
            speed = 0
            update_progress(resume_pos, file_size, speed)
            print(f'\n第{attempt_count}次尝试失败')
            print(f'当前已下载：{format_size(resume_pos)}/{format_size(file_size)}')
            print(f'等待{retry_interval}秒后自动重试...')
            time.sleep(retry_interval)
        except KeyboardInterrupt:
            # 用户中断处理
            speed = 0
            update_progress(resume_pos, file_size, speed)
            print(f'\n\n用户中断下载，已保存进度：{format_size(resume_pos)}')
            print(f'文件路径：{file_path}（再次执行脚本可继续下载）')
            return False
        except Exception as e:
            # 其他未知异常处理
            speed = 0
            update_progress(resume_pos, file_size, speed)
            print(f'\n未知错误: {str(e)}')
            print(f'等待{retry_interval}秒后自动重试...')
            time.sleep(retry_interval)

    # 第七步：返回最终结果
    if success:
        update_progress(file_size, file_size, 0)
        print(f'\n\n下载完成！文件保存至：{file_path}')
        return True

def get_user_input():
    """
    交互式用户输入获取器
    
    通过命令行交互获取下载链接。
    
    Returns:
        str: 下载链接
    """
    # 获取下载链接
    while True:
        url = input("请输入下载链接: ").strip()
        if url:
            break
        print("下载链接不能为空，请重新输入！")
    
    print(f"开始下载: {url}")
    
    return url

def main():
    """
    程序入口点 - 交互式界面
    
    提供友好的命令行交互界面，引导用户输入下载参数。
    无需命令行参数，启动后通过交互获取所有必要信息。
    
    交互流程：
    1. 获取下载链接（必填）
    2. 直接开始下载（重试延迟固定为0秒）
    
    注意事项：
    • 支持HTTP/HTTPS下载，自动处理SSL证书验证问题
    • 支持Ctrl+C中断并保存下载进度
    • 自动检测文件完整性，损坏文件会重新下载
    """
    # 获取用户输入
    url = get_user_input()
    
    # 启动下载
    download_with_auto_resume(url)

if __name__ == '__main__':
    main()