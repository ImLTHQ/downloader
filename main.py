import os
import sys
import argparse
import time
import requests
from pathlib import Path
from urllib.parse import urlparse
import urllib3

# 屏蔽SSL警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_download_path():
    """获取系统默认下载文件夹"""
    if sys.platform == 'win32':
        download_path = Path(os.environ['USERPROFILE']) / 'Downloads'
    elif sys.platform == 'darwin':
        download_path = Path(os.environ['HOME']) / 'Downloads'
    else:
        download_path = Path(os.environ['HOME']) / 'Downloads'
    download_path.mkdir(exist_ok=True)
    return download_path

def get_filename_from_url(url):
    """提取文件名（去除URL参数）"""
    parsed_url = urlparse(url)
    filename = os.path.basename(parsed_url.path)
    if not filename:
        filename = 'download_file'
    filename = filename.split('?')[0]
    return filename

def update_progress(downloaded, total):
    """可视化进度条"""
    bar_length = 50
    if total == 0:
        percent = 100
    else:
        percent = downloaded / total * 100
    filled_length = int(bar_length * downloaded // total)
    bar = '█' * filled_length + '-' * (bar_length - filled_length)

    # 字节数格式化
    def format_size(size):
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        unit_idx = 0
        while size >= 1024 and unit_idx < len(units)-1:
            size /= 1024
            unit_idx += 1
        return f"{size:.2f} {units[unit_idx]}"
    
    downloaded_str = format_size(downloaded)
    total_str = format_size(total)
    sys.stdout.write(f'\r下载进度：|{bar}| {percent:.1f}% ({downloaded_str}/{total_str})')
    sys.stdout.flush()

def check_file_integrity(file_path, expected_size):
    """校验文件完整性"""
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

def download_with_auto_resume(url, proxy=None, max_attempts=100):
    """核心功能：断连后自动续传，直到下载完成或达到最大尝试次数"""
    download_dir = get_download_path()
    filename = get_filename_from_url(url)
    file_path = download_dir / filename
    proxies = {'http': proxy, 'https': proxy} if proxy else None

    # 1. 获取文件总大小
    try:
        head_response = requests.head(url, proxies=proxies, timeout=15, verify=False, allow_redirects=True)
        head_response.raise_for_status()
        file_size = int(head_response.headers.get('Content-Length', 0))
        if file_size == 0:
            print('无法获取文件大小，下载失败')
            return False
    except Exception as e:
        print(f'获取文件信息失败：{e}')
        return False

    # 2. 初始化参数
    attempt_count = 0
    resume_pos = 0
    success = False

    print(f'开始下载：{filename}（总大小：{format_size(file_size)}）')
    print(f'代理地址：{proxy if proxy else "无"}')
    print(f'最大自动续传次数：{max_attempts}')

    while attempt_count < max_attempts and not success:
        attempt_count += 1
        # 检查现有文件进度
        if os.path.exists(file_path):
            current_size = os.path.getsize(file_path)
            if current_size >= file_size:
                if check_file_integrity(file_path, file_size):
                    print(f'\n文件已完整！保存至：{file_path}')
                    success = True
                    break
                else:
                    os.remove(file_path)
                    resume_pos = 0
            else:
                resume_pos = current_size
        else:
            resume_pos = 0

        # 跳过已完成的情况
        if resume_pos >= file_size:
            success = True
            break

        print(f'\n第{attempt_count}次尝试：从{format_size(resume_pos)}开始续传')
        try:
            # 构建请求头（断点续传）
            headers = {'Range': f'bytes={resume_pos}-'}
            session = requests.Session()
            adapter = requests.adapters.HTTPAdapter(max_retries=5)
            session.mount('http://', adapter)
            session.mount('https://', adapter)

            response = session.get(
                url,
                headers=headers,
                proxies=proxies,
                stream=True,
                timeout=300,  # 5分钟超时，适配慢代理
                verify=False,
                allow_redirects=True
            )
            response.raise_for_status()

            # 写入文件
            mode = 'ab' if resume_pos > 0 else 'wb'
            with open(file_path, mode) as f:
                downloaded_in_this_attempt = 0
                for chunk in response.iter_content(chunk_size=4096):
                    if chunk:
                        f.write(chunk)
                        resume_pos += len(chunk)
                        downloaded_in_this_attempt += len(chunk)
                        update_progress(resume_pos, file_size)

            # 检查本次尝试后是否完成
            if check_file_integrity(file_path, file_size):
                success = True
                break

        except requests.exceptions.RequestException as e:
            print(f'\n第{attempt_count}次尝试失败：{e}')
            print(f'当前已下载：{format_size(resume_pos)}/{format_size(file_size)}')
            print('等待5秒后自动重试...')
            time.sleep(5)  # 失败后等待5秒再重试，降低代理压力
        except KeyboardInterrupt:
            print(f'\n用户中断下载，已保存进度：{format_size(resume_pos)}')
            return False
        except Exception as e:
            print(f'\n未知错误：{e}')
            time.sleep(5)

    # 最终结果
    if success:
        update_progress(file_size, file_size)
        print(f'\n下载完成！文件保存至：{file_path}')
        return True
    else:
        print(f'\n达到最大尝试次数（{max_attempts}次），下载失败')
        print(f'最后进度：{format_size(resume_pos)}/{format_size(file_size)}')
        return False

def format_size(size):
    """辅助函数：字节数格式化"""
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    unit_idx = 0
    while size >= 1024 and unit_idx < len(units)-1:
        size /= 1024
        unit_idx += 1
    return f"{size:.2f} {units[unit_idx]}"

def main():
    parser = argparse.ArgumentParser(description='断连自动续传下载工具（适配不稳定代理）')
    parser.add_argument('-l', '--link', required=True, help='下载链接（必填）')
    parser.add_argument('-p', '--proxy', default=None, help='HTTP代理，格式如127.0.0.1:6666')
    parser.add_argument('-m', '--max-attempts', type=int, default=100, help='最大自动重试次数，默认100')
    args = parser.parse_args()

    download_with_auto_resume(args.link, args.proxy, args.max_attempts)

if __name__ == '__main__':
    main()