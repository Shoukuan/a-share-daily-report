"""
发布模块
负责将报告发布到飞书（文档 + 消息通知）

设计原则：
- 开发环境：使用模拟实现，便于测试
- OpenClaw环境：优先调用 openclaw.tools 中的 feishu_create_doc / feishu_im_user_message
"""

import json
import os
from datetime import datetime

from utils import (
    cn_now,
    ensure_trace_id,
    format_date,
    get_logger,
    load_project_env,
    log_event,
    monitor_stage,
)

logger = get_logger('publisher')


class Publisher:
    """发布类"""

    def __init__(self, config):
        self.config = config
        self.publish_config = config.get('publish', {})
        self._feishu_create_doc = None
        self._feishu_im_user_message = None

        # dry_run: 强制使用模拟实现，即使在 OpenClaw 环境中也不发送真实请求
        # 优先级: 环境变量 > 配置文件
        self.dry_run = (
            os.environ.get('A_SHARE_DRY_RUN', '').lower() in ('1', 'true', 'yes')
            or bool(self.publish_config.get('dry_run', False))
        )

        self.in_openclaw = (not self.dry_run) and self._detect_openclaw()
        if self.in_openclaw:
            self._load_openclaw_tools()

        env_label = 'dry_run(模拟)' if self.dry_run else ('OpenClaw' if self.in_openclaw else '开发/模拟')
        logger.info(f"Publisher 初始化完成（环境: {env_label}）")

    def _detect_openclaw(self):
        """检测是否在 OpenClaw 环境中运行"""
        if os.environ.get('OPENCLAW_RUNTIME'):
            return True
        try:
            from openclaw import tools as _tools  # noqa: F401
            return True
        except Exception:
            return False

    def _load_openclaw_tools(self):
        """加载 OpenClaw 飞书工具。"""
        try:
            from openclaw.tools import feishu_create_doc, feishu_im_user_message

            self._feishu_create_doc = feishu_create_doc
            self._feishu_im_user_message = feishu_im_user_message
            log_event(logger, 'info', 'openclaw_tools_loaded', available=True)
        except Exception as e:
            self._feishu_create_doc = None
            self._feishu_im_user_message = None
            log_event(logger, 'warning', 'openclaw_tools_load_failed', error=str(e))

    def publish_morning_report(self, markdown_content, report_date, send_notification=False):
        return self._publish_report(markdown_content, report_date, 'morning', send_notification)

    def publish_evening_report(self, markdown_content, report_date, send_notification=False):
        return self._publish_report(markdown_content, report_date, 'evening', send_notification)

    @monitor_stage('publisher.publish_report')
    def _publish_report(self, markdown_content, report_date, mode, send_notification):
        """统一发布逻辑"""
        ensure_trace_id()
        try:
            title = f"A股{'早报' if mode == 'morning' else '晚报'}-{format_date(report_date, '%Y%m%d')}"

            doc_id, doc_url = self._create_document(title, markdown_content)

            result = {
                'success': True,
                'doc_id': doc_id,
                'doc_url': doc_url,
                'title': title,
                'published_at': format_date(cn_now(), '%Y-%m-%d %H:%M:%S'),
            }

            if send_notification:
                message_result = self._send_notification(title, doc_url, report_date, mode)
                result['notification_sent'] = message_result.get('success', False)
                result['notification_message_id'] = message_result.get('message_id')

            log_event(logger, 'info', 'publish_done', mode=mode, doc_id=doc_id, doc_url=doc_url)
            return result

        except Exception as e:
            logger.error(f"❌ {mode}发布失败: {e}")
            return {'success': False, 'error': str(e)}

    def _create_document(self, title, markdown_content):
        """创建飞书文档（根据环境选择实现）"""
        if self.dry_run:
            logger.info("🔒 dry_run 模式：跳过真实文档创建")
            return self._create_document_mock(title, markdown_content)
        if self.in_openclaw:
            return self._create_document_real(title, markdown_content)
        return self._create_document_mock(title, markdown_content)

    @monitor_stage('publisher.create_document.real')
    def _create_document_real(self, title, markdown_content):
        """真实工具调用（OpenClaw MCP）"""
        logger.info("🌍 检测到 OpenClaw 环境，调用 feishu_create_doc 工具...")

        if self._feishu_create_doc is None:
            self._load_openclaw_tools()
        if self._feishu_create_doc is None:
            raise RuntimeError('openclaw.tools.feishu_create_doc 不可用')

        folder_token = self.publish_config.get('feishu_doc', {}).get('folder_token') or None
        result = self._feishu_create_doc(title=title, markdown=markdown_content, folder_token=folder_token)

        doc_id, doc_url = self._parse_doc_result(result)
        if not doc_id:
            raise RuntimeError(f"创建文档失败，返回结构缺少 doc_id/token: {result}")

        log_event(logger, 'info', 'feishu_doc_created', doc_id=doc_id, doc_url=doc_url)
        return doc_id, doc_url

    def _create_document_mock(self, title, markdown_content):
        """模拟创建文档（开发阶段）"""
        mock_id = f"doxcn_mock_{format_date(cn_now(), '%Y%m%d%H%M%S')}"
        mock_url = f"https://example.feishu.cn/docx/{mock_id}"
        logger.info(f"  模拟文档ID: {mock_id}")
        logger.info(f"  模拟文档链接: {mock_url}")
        return mock_id, mock_url

    def _send_notification(self, title, doc_url, report_date, mode):
        """发送通知消息（根据环境选择实现）"""
        user_open_id = self._get_user_open_id()
        if not user_open_id:
            logger.warning("⚠️ 未配置 user_open_id，跳过消息发送")
            return {'success': False, 'error': '未配置用户ID'}

        if self.dry_run:
            logger.info("🔒 dry_run 模式：跳过真实消息发送")
            return self._send_notification_mock(title, doc_url, report_date, mode, user_open_id)
        if self.in_openclaw:
            return self._send_notification_real(title, doc_url, report_date, mode, user_open_id)
        return self._send_notification_mock(title, doc_url, report_date, mode, user_open_id)

    @monitor_stage('publisher.send_notification.real')
    def _send_notification_real(self, title, doc_url, report_date, mode, user_open_id):
        """真实消息发送（OpenClaw 环境）"""
        try:
            mode_text = '早报' if mode == 'morning' else '晚报'
            date_str = format_date(report_date, '%Y年%m月%d日')
            message_text = f"""【{mode_text}已生成】

📅 日期：{date_str}
📄 标题：{title}
🔗 文档：{doc_url}

请查看以上链接获取完整报告。"""

            logger.info('🌍 发送消息（OpenClaw 环境）...')
            if self._feishu_im_user_message is None:
                self._load_openclaw_tools()
            if self._feishu_im_user_message is None:
                raise RuntimeError('openclaw.tools.feishu_im_user_message 不可用')

            receive_id_type = self.publish_config.get('feishu_message', {}).get('receive_id_type')
            if not receive_id_type:
                receive_id_type = 'chat_id' if str(user_open_id).startswith('oc_') else 'open_id'

            result = self._feishu_im_user_message(
                action='send',
                msg_type='text',
                content=json.dumps({'text': message_text}, ensure_ascii=False),
                receive_id_type=receive_id_type,
                receive_id=user_open_id,
            )

            message_id = self._parse_message_id(result)
            log_event(
                logger,
                'info',
                'feishu_message_sent',
                receive_id_type=receive_id_type,
                message_id=message_id or '',
            )
            return {'success': True, 'message_id': message_id}

        except Exception as e:
            logger.error(f'发送通知失败: {e}')
            return {'success': False, 'error': str(e)}

    def _send_notification_mock(self, title, doc_url, report_date, mode, user_open_id):
        """模拟发送消息（开发阶段）"""
        mode_text = '早报' if mode == 'morning' else '晚报'
        date_str = format_date(report_date, '%Y年%m月%d日')
        message_preview = f"【{mode_text}已生成】 {date_str} {title}"
        logger.info(f'📱 [MOCK] 发送消息给 {user_open_id}')
        logger.info(f'   预览: {message_preview}')
        return {
            'success': True,
            'message_id': f"mock_msg_{format_date(cn_now(), '%Y%m%d%H%M%S')}",
        }

    def _parse_doc_result(self, result):
        """解析 feishu_create_doc 返回结构。"""
        if result is None:
            return None, None

        candidates = [result]
        if isinstance(result, dict):
            if isinstance(result.get('data'), dict):
                candidates.append(result['data'])
            if isinstance(result.get('result'), dict):
                candidates.append(result['result'])

        for item in candidates:
            if not isinstance(item, dict):
                continue
            doc_id = (
                item.get('doc_id')
                or item.get('token')
                or item.get('doc_token')
                or item.get('obj_token')
                or item.get('document_id')
            )
            doc_url = item.get('doc_url') or item.get('url') or item.get('link')
            if doc_id:
                if not doc_url:
                    doc_url = f'https://open.feishu.cn/document/{doc_id}'
                return str(doc_id), str(doc_url)

        return None, None

    def _parse_message_id(self, result):
        """解析 feishu_im_user_message 返回结构。"""
        if result is None:
            return None
        if isinstance(result, dict):
            if result.get('message_id'):
                return str(result.get('message_id'))
            if result.get('msg_id'):
                return str(result.get('msg_id'))
            data = result.get('data')
            if isinstance(data, dict) and data.get('message_id'):
                return str(data.get('message_id'))
        return None

    def _get_user_open_id(self):
        """获取用户 open_id（多源Fallback）"""
        user_id = self.publish_config.get('feishu_message', {}).get('target_chat_id')
        if user_id:
            logger.debug(f'从配置获取 user_open_id: {user_id}')
            return user_id

        user_id = os.environ.get('FEISHU_NOTIFY_OPEN_ID')
        if user_id:
            logger.debug(f'从 FEISHU_NOTIFY_OPEN_ID 获取: {user_id}')
            return user_id

        user_id = os.environ.get('FEISHU_USER_OPEN_ID')
        if user_id:
            logger.debug(f'从 FEISHU_USER_OPEN_ID 获取: {user_id}')
            return user_id

        load_project_env(override=False)
        user_id = os.getenv('FEISHU_NOTIFY_OPEN_ID') or os.getenv('FEISHU_USER_OPEN_ID')
        if user_id:
            logger.debug(f'从 .env 文件加载: {user_id}')
            return user_id

        logger.warning('未找到 user_open_id 配置')
        return None

    @monitor_stage('publisher.convert_pdf.wkhtmltopdf')
    def convert_to_pdf(self, markdown_content, output_path, title=None):
        """PDF转换（可选功能）"""
        try:
            import subprocess
            import tempfile

            html_content = self._markdown_to_html(markdown_content, title)

            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', encoding='utf-8') as f:
                f.write(html_content)
                html_path = f.name

            logger.info(f'📄 转换PDF: {output_path}')
            result = subprocess.run(
                ['wkhtmltopdf', html_path, output_path],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                logger.info(f'✅ PDF转换成功: {output_path}')
                return {'success': True, 'pdf_path': output_path}
            raise RuntimeError(result.stderr)

        except (FileNotFoundError, RuntimeError) as e:
            logger.warning(f'⚠️ PDF转换不可用: {e}')
            logger.info('  提示: 安装 wkhtmltopdf: brew install wkhtmltopdf (macOS)')
            return {'success': False, 'error': str(e)}

    def _markdown_to_html(self, markdown_content, title=None):
        """Markdown → HTML"""
        try:
            import markdown

            html = markdown.markdown(
                markdown_content,
                extensions=['tables', 'fenced_code', 'codehilite'],
            )
        except ImportError:
            html = markdown_content.replace('\n', '<br>')

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset=\"UTF-8\">
            <title>{title or 'A股日报'}</title>
            <style>
                body {{ font-family: \"PingFang SC\", \"Microsoft YaHei\", sans-serif; margin: 40px; line-height: 1.6; }}
                h1, h2, h3 {{ color: #333; margin-top: 24px; border-bottom: 1px solid #eee; padding-bottom: 8px; }}
                table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
                th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
                th {{ background-color: #f5f5f5; font-weight: bold; }}
                code {{ background-color: #f5f5f5; padding: 2px 4px; border-radius: 3px; }}
                pre {{ background-color: #f5f5f5; padding: 12px; border-radius: 4px; overflow-x: auto; }}
            </style>
        </head>
        <body>
            <h1>{title or 'A股日报'}</h1>
            {html}
        </body>
        </html>
        """
