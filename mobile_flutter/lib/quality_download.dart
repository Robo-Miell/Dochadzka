import 'dart:convert';
import 'dart:typed_data';
import 'package:http/http.dart' as http;

class QualityReport {
  final String name;
  final Uint8List bytes;
  QualityReport(this.name, this.bytes);
}

Future<QualityReport> fetchQualityReport(http.Client client, Uri origin, String path, String token) async {
  final uri = origin.resolve(path);
  if (uri.origin != origin.origin || uri.userInfo.isNotEmpty ||
      !RegExp(r'^/quality/api/export/(pdf|xlsx|daily-xlsm|records-pdf|records-xlsx)$').hasMatch(uri.path)) {
    throw Exception('Neplatný odkaz na report.');
  }
  final request = http.Request('GET', uri)..followRedirects = false;
  request.headers['Authorization'] = 'Bearer $token';
  final response = await client.send(request).then(http.Response.fromStream).timeout(const Duration(seconds: 120));
  if (response.statusCode != 200) {
    if (response.statusCode == 401) throw Exception('Prihlásenie vypršalo. Prihlás sa znova.');
    String detail = 'Report sa nepodarilo stiahnuť (HTTP ${response.statusCode}).';
    try {
      final body = jsonDecode(utf8.decode(response.bodyBytes));
      detail = (body['error'] ?? body['detail'] ?? detail).toString();
    } catch (_) {}
    throw Exception(detail);
  }
  final bytes = response.bodyBytes;
  final pdf = uri.path.endsWith('pdf');
  final valid = pdf
    ? bytes.length >= 5 && ascii.decode(bytes.sublist(0, 5), allowInvalid: true) == '%PDF-'
    : bytes.length >= 4 && bytes[0] == 80 && bytes[1] == 75 && bytes[2] == 3 && bytes[3] == 4;
  if (!valid) throw Exception('Server nevrátil platný súbor reportu.');
  final extension = pdf ? 'pdf' : uri.path.endsWith('daily-xlsm') ? 'xlsm' : 'xlsx';
  final disposition = response.headers['content-disposition'] ?? '';
  final match = RegExp(r'filename="?([^";]+)', caseSensitive: false).firstMatch(disposition);
  var name = (match?.group(1) ?? 'MIELL_Report.$extension').split(RegExp(r'[/\\]')).last;
  name = name.replaceAll(RegExp(r'[<>:"|?*\x00-\x1f]'), '_');
  if (!name.toLowerCase().endsWith('.$extension')) name = 'MIELL_Report.$extension';
  return QualityReport(name, bytes);
}
