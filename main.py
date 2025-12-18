import os
import sys
import argparse
import time
import requests
from pathlib import Path
from urllib.parse import urlparse
import urllib3

# SSL警告将在需要时屏蔽

def get_download_path():
    #   获取系统默认下载文件夹
    if sys.platform == 'win32':
        download_path = Path(os.environ['USERPROFILE']) / 'Downloads'
    elif sys.platform == 'darwin':
        download_path = Path(os.environ['HOME']) / 'Downloads'
    else:
        download_path = Path(os.environ['HOME']) / 'Downloads'
    download_path.mkdir(exist_ok=True)
    return download_path

def get_filename_from_url(url):
    #   提取文件名（去除URL参数）
    parsed_url = urlparse(url)
    filename = os.path.basename(parsed_url.path)
    if not filename:
        filename = 'download_file'
    filename = filename.split('?')[0]
    return filename

def format_size(size):
    #   字节数格式化(B/KB/MB/GB)
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    unit_idx = 0
    while size >= 1024 and unit_idx < len(units)-1:
        size /= 1024
        unit_idx += 1
    return f"{size:.2f} {units[unit_idx]}"

def update_progress(downloaded, total, speed):
    #   显示百分比 + 已下载/总大小 + 速率（无进度条）
    if total == 0:
        percent = 100
    else:
        percent = downloaded / total * 100

    # 格式化速率（字节/秒 → KB/s/MB/s）
    speed_str = format_size(speed) + '/s'
    
    downloaded_str = format_size(downloaded)
    total_str = format_size(total)
    # 输出进度（覆盖当前行）
    sys.stdout.write(f'\r{percent:.1f}% ({downloaded_str}/{total_str}) {speed_str}')
    sys.stdout.flush()

def check_file_integrity(file_path, expected_size):
    #   校验文件完整性
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

def download_with_auto_resume(url, proxy=None, retry_interval=3, ignore_ssl_errors=False):
    #   重试 + 无限续传 + 速率显示
    # 根据参数决定是否屏蔽SSL警告
    if ignore_ssl_errors:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    download_dir = get_download_path()
    filename = get_filename_from_url(url)
    file_path = download_dir / filename
    proxies = {'http': proxy, 'https': proxy} if proxy else None

    # 1. 获取文件总大小
    try:
        head_response = requests.head(url, proxies=proxies, timeout=10, verify=not ignore_ssl_errors, allow_redirects=True)
        head_response.raise_for_status()
        file_size = int(head_response.headers.get('Content-Length', 0))
        if file_size == 0:
            if not ignore_ssl_errors:
                print('无法获取文件大小，下载失败')
            return False
    except Exception as e:
        if not ignore_ssl_errors:
            print(f'获取文件信息失败：{e}')
        return False

    # 2. 初始化参数
    resume_pos = 0
    attempt_count = 0
    success = False

    print(f'开始下载：{filename}（总大小：{format_size(file_size)}）')
    print(f'重试间隔：{retry_interval}秒')

    # 无限重试直到下载完成或用户中断
    while not success:
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
                timeout=10,  # 10秒超时
                verify=not ignore_ssl_errors,
                allow_redirects=True
            )
            response.raise_for_status()

            # 写入文件 + 计算实时速率
            mode = 'ab' if resume_pos > 0 else 'wb'
            with open(file_path, mode) as f:
                downloaded_in_this_attempt = 0
                start_time = time.time()
                last_check_time = start_time
                last_downloaded = resume_pos

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

            # 检查本次尝试后是否完成
            if check_file_integrity(file_path, file_size):
                success = True
                break

        except requests.exceptions.RequestException as e:
            # 计算本次尝试的最终速率
            speed = 0
            update_progress(resume_pos, file_size, speed)
            if not ignore_ssl_errors:
                print(f'\n第{attempt_count}次尝试失败：{e}')
            else:
                print(f'\n第{attempt_count}次尝试失败')
            print(f'当前已下载：{format_size(resume_pos)}/{format_size(file_size)}')
            print(f'等待{retry_interval}秒后自动重试...')
            time.sleep(retry_interval)  # 3秒重试间隔
        except KeyboardInterrupt:
            # 用户中断时显示最终进度
            speed = 0
            update_progress(resume_pos, file_size, speed)
            print(f'\n\n用户中断下载，已保存进度：{format_size(resume_pos)}')
            print(f'文件路径：{file_path}（再次执行脚本可继续下载）')
            return False
        except Exception as e:
            speed = 0
            update_progress(resume_pos, file_size, speed)
            if not ignore_ssl_errors:
                print(f'\n未知错误：{e}')
            else:
                print(f'\n未知错误')
            print(f'等待{retry_interval}秒后自动重试...')
            time.sleep(retry_interval)

    # 最终结果
    if success:
        update_progress(file_size, file_size, 0)
        print(f'\n\n下载完成！文件保存至：{file_path}')
        return True

def main():
    parser = argparse.ArgumentParser(description='下载工具')
    parser.add_argument('-l', '--link', required=True, help='下载链接 (必填)')
    parser.add_argument('-p', '--proxy', default=None, help='HTTP代理 格式: 127.0.0.1:6666')
    parser.add_argument('-r', '--retry-interval', type=int, default=3, help='重试间隔')
    parser.add_argument('-i', '--ignore-ssl-errors', action='store_true', help='忽略SSL警告且不显示下载失败原因')
    args = parser.parse_args()

    download_with_auto_resume(args.link, args.proxy, args.retry_interval, args.ignore_ssl_errors)

if __name__ == '__main__':
    main()