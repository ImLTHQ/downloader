"""
文件下载工具 - 支持断点续传、代理、SSL错误忽略
功能：
1. 断点续传下载
2. 自动重试机制
3. HTTP/HTTPS代理支持
4. 实时下载速度显示
5. 文件完整性校验
6. SSL证书验证控制
"""

import os
import sys
import argparse
import time
import requests
from pathlib import Path
from urllib.parse import urlparse
import urllib3

def get_download_path():
    """
    获取Windows系统默认下载文件夹
    Returns:
        Path: 下载目录路径对象
    """
    download_path = Path(os.environ['USERPROFILE']) / 'Downloads'
    download_path.mkdir(exist_ok=True)
    return download_path

def get_filename_from_url(url):
    """
    从URL中提取文件名（去除URL参数）
    Args:
        url (str): 下载链接
    Returns:
        str: 提取的文件名
    """
    parsed_url = urlparse(url)
    filename = os.path.basename(parsed_url.path)
    if not filename:
        filename = 'download_file'
    filename = filename.split('?')[0]
    return filename

def format_size(size):
    """
    将字节数格式化为人类可读的单位
    Args:
        size (int): 字节数
    Returns:
        str: 格式化后的大小字符串（如：1.23 MB）
    """
    units = ['B', 'KB', 'MB']
    unit_idx = 0
    while size >= 1024 and unit_idx < len(units)-1:
        size /= 1024
        unit_idx += 1
    return f"{size:.2f} {units[unit_idx]}"

def update_progress(downloaded, total, speed):
    """
    实时更新下载进度显示
    Args:
        downloaded (int): 已下载字节数
        total (int): 总文件大小
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
    # 输出进度（覆盖当前行）
    sys.stdout.write(f'\r{percent:.1f}% ({downloaded_str}/{total_str}) {speed_str}')
    sys.stdout.flush()

def check_file_integrity(file_path, expected_size):
    """
    校验文件完整性（大小和内容）
    Args:
        file_path (Path): 文件路径
        expected_size (int): 期望的文件大小
    Returns:
        bool: 文件完整性校验结果
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

def create_proxies(proxy_url):
    """
    创建代理配置字典，支持HTTP和HTTPS代理
    Args:
        proxy_url (str): 代理URL，支持多种格式
    Returns:
        dict: 代理配置字典，包含http和https键
    """
    if not proxy_url:
        return None
    
    # 自动检测代理协议并补全
    if not proxy_url.startswith(('http://', 'https://', 'socks5://')):
        # 默认使用HTTP代理
        proxy_url = f'http://{proxy_url}'
    
    # 同时设置HTTP和HTTPS代理
    return {
        'http': proxy_url,
        'https': proxy_url
    }

def download_with_auto_resume(url, proxy=None, retry_interval=3, ignore_ssl_errors=False):
    """
    自动断点续传下载函数
    支持功能：
    - 断点续传
    - 无限重试机制
    - 实时速度显示
    - HTTP/HTTPS代理支持
    - SSL证书验证控制
    
    Args:
        url (str): 下载链接
        proxy (str): 代理地址（支持格式：127.0.0.1:6666, http://127.0.0.1:6666, https://127.0.0.1:6666, socks5://127.0.0.1:1080）
        retry_interval (int): 重试间隔（秒）
        ignore_ssl_errors (bool): 是否忽略SSL错误
        
    Returns:
        bool: 下载是否成功
    """
    # 根据参数决定是否屏蔽SSL警告
    if ignore_ssl_errors:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    download_dir = get_download_path()
    filename = get_filename_from_url(url)
    file_path = download_dir / filename
    proxies = create_proxies(proxy)

# 第一步：获取文件总大小和服务器信息
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

# 第二步：初始化下载参数
    resume_pos = 0
    attempt_count = 0
    success = False

    print(f'开始下载：{filename}（总大小：{format_size(file_size)}）')
    if proxy:
        print(f'使用代理：{proxy}')
    print(f'重试间隔：{retry_interval}秒')

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

        print(f'\n第{attempt_count}次尝试：从{format_size(resume_pos)}开始续传')
        try:
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
                verify=not ignore_ssl_errors,
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
            if not ignore_ssl_errors:
                print(f'\n第{attempt_count}次尝试失败：{e}')
            else:
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
            if not ignore_ssl_errors:
                print(f'\n未知错误：{e}')
            else:
                print(f'\n未知错误')
            print(f'等待{retry_interval}秒后自动重试...')
            time.sleep(retry_interval)

    # 第七步：返回最终结果
    if success:
        update_progress(file_size, file_size, 0)
        print(f'\n\n下载完成！文件保存至：{file_path}')
        return True

def main():
    """
    主函数：解析命令行参数并启动下载
    支持的代理格式：
    - HTTP代理：127.0.0.1:6666 或 http://127.0.0.1:6666
    - HTTPS代理：https://127.0.0.1:6666
    - SOCKS5代理：socks5://127.0.0.1:1080
    """
    parser = argparse.ArgumentParser(
        description='强大的文件下载工具 - 支持断点续传、代理、重试机制'
    )
    
    parser.add_argument('-l', '--link', required=True, 
                       help='下载链接 (必填)')
    parser.add_argument('-p', '--proxy', default=None, 
                       help='代理地址 (支持HTTP/HTTPS/SOCKS5代理，格式：127.0.0.1:6666 或 http://127.0.0.1:6666)')
    parser.add_argument('-r', '--retry-interval', type=int, default=3, 
                       help='重试间隔（秒，默认3秒）')
    parser.add_argument('-i', '--ignore', action='store_true', 
                       help='忽略SSL警告且不显示详细错误信息')
    
    args = parser.parse_args()

    # 启动下载
    download_with_auto_resume(args.link, args.proxy, args.retry_interval, args.ignore)

if __name__ == '__main__':
    main()