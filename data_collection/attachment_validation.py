"""Check container signatures before accepting a downloaded document."""
import io
import zipfile


def validate_attachment(data, suffix):
    prefix = data[:1024].lstrip().lower()
    if not data:
        raise ValueError('附件为空')
    if prefix.startswith((b'<!doctype html', b'<html', b'<?xml')) or b'<html' in prefix:
        raise ValueError('附件实际为 HTML/XML 页面，可能是错误页或验证页')
    if suffix in {'.xlsx', '.docx'}:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = set(archive.namelist())
                required = '[Content_Types].xml'
                main = 'xl/workbook.xml' if suffix == '.xlsx' else 'word/document.xml'
                if required not in names or main not in names:
                    raise ValueError('附件容器内容与扩展名不符')
                if sum(info.file_size for info in archive.infolist()) > 150 * 1024 * 1024:
                    raise ValueError('附件解压大小超过 150 MB')
                if archive.testzip() is not None:
                    raise ValueError('附件 ZIP 校验失败')
        except zipfile.BadZipFile as exc:
            raise ValueError('附件不是有效的 Office ZIP 文档') from exc
    elif suffix == '.pdf':
        if not data.startswith(b'%PDF-'):
            raise ValueError('附件缺少 PDF 文件标识')
    elif suffix in {'.xls', '.doc'}:
        if not data.startswith(bytes.fromhex('D0CF11E0A1B11AE1')):
            raise ValueError('附件缺少旧版 Office 容器标识')
    elif suffix == '.csv':
        if b'\x00' in data[:4096]:
            raise ValueError('CSV 包含二进制或暂不支持的编码，需人工核查')
