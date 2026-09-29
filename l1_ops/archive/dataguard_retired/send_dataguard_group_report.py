#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DataGuard 群组投送脚本 - 2026-05-28
使用直连通道进行投送
"""

import os
import subprocess
import json
from pathlib import Path

def send_dataguard_report():
    """发送DataGuard报告到工作群"""
    
    # 读取生成的群组报告
    report_path = Path("/mnt/c/new_tdx64/PYPlugins/user/dataguard_group_report_20260528.txt")
    
    if not report_path.exists():
        print("❌ 群组报告文件不存在")
        return False
    
    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            report_content = f.read()
    except Exception as e:
        print(f"❌ 读取报告文件失败: {e}")
        return False
    
    # 添加投送标记
    delivery_header = """📋 DataGuard 投送通知 - 2026-05-28

本消息由系统自动生成，基于DataGuard验证结果：

"""
    
    delivery_content = delivery_header + report_content
    
    # 使用直连通道投送（根据技能中的方法）
    env_vars = {
        'HERMES_CRON_AUTO_DELIVER_PLATFORM': '',
        'HERMES_CRON_AUTO_DELIVER_CHAT_ID': '',
        'HERMES_CRON_AUTO_DELIVER_THREAD_ID': ''
    }
    
    # 创建临时投送文件
    temp_file = Path("/tmp/dataguard_delivery_20260528.txt")
    try:
        with open(temp_file, 'w', encoding='utf-8') as f:
            f.write(delivery_content)
        
        # 使用直连通道发送
        cmd = [
            'env', 
            '-u', 'HERMES_CRON_AUTO_DELIVER_PLATFORM',
            '-u', 'HERMES_CRON_AUTO_DELIVER_CHAT_ID', 
            '-u', 'HERMES_CRON_AUTO_DELIVER_THREAD_ID',
            'hermes', 'send', 
            '--to', 'feishu:oc_b20afb335526605f263e698445c93ce2',
            '--file', str(temp_file)
        ]
        
        print("🚀 执行直连投送...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            print("✅ 直连投送成功")
            print(f"返回结果: {result.stdout}")
            
            # 保存投送结果
            save_delivery_result(delivery_content, result.stdout)
            
            # 清理临时文件
            temp_file.unlink()
            return True
        else:
            print(f"❌ 直连投送失败: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ 投送过程出错: {e}")
        return False
    finally:
        # 确保清理临时文件
        if temp_file.exists():
            temp_file.unlink()

def save_delivery_result(report_content, delivery_result):
    """保存投送结果到本地"""
    
    timestamp = "20260528"
    
    # 保存投送成功的报告副本
    delivery_copy = Path("/mnt/d/DataGuard_Report_20260528.txt")
    try:
        with open(delivery_copy, 'w', encoding='utf-8') as f:
            f.write(report_content)
        print(f"✅ 投送副本保存: {delivery_copy}")
    except Exception as e:
        print(f"⚠️ 保存副本失败: {e}")
    
    # 保存投送结果
    result_file = Path("/mnt/c/new_tdx64/PYPlugins/user/dataguard_delivery_result_20260528.txt")
    try:
        with open(result_file, 'w', encoding='utf-8') as f:
            f.write(f"投送时间: {timestamp}\n")
            f.write(f"投送结果: {delivery_result}\n")
            f.write("完整报告内容:\n")
            f.write("-" * 50 + "\n")
            f.write(report_content)
        print(f"✅ 投送结果保存: {result_file}")
    except Exception as e:
        print(f"⚠️ 保存投送结果失败: {e}")

def main():
    """主函数"""
    print("=" * 60)
    print("DataGuard 群组投送脚本")
    print("=" * 60)
    print("目标: 工作群投送 - 2026-05-28")
    print("路由: group (有未解决问题)")
    print("=" * 60)
    
    # 发送报告
    success = send_dataguard_report()
    
    if success:
        print("\n✅ 投送完成")
        print("[SILENT]")  # 抑制自动投送，避免重复
        return 0
    else:
        print("\n❌ 投送失败")
        print("请检查网络连接和工具配置")
        return 1

if __name__ == "__main__":
    import sys
    sys.exit(main())