import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:dochadzka_mobile/quality_download.dart';

void main() {
  final origin = Uri.parse('https://example.test');
  test('PDF request uses operator token and preserves the file', () async {
    final client = MockClient((request) async {
      expect(request.headers['Authorization'], 'Bearer operator-test');
      expect(request.url.queryParameters['job_id'], '3');
      return http.Response('%PDF-1.4 test', 200, headers: {'content-disposition':'attachment; filename="report.pdf"'});
    });
    final report = await fetchQualityReport(client, origin, '/quality/api/export/pdf?job_id=3', 'operator-test');
    expect(report.name, 'report.pdf');
    expect(utf8.decode(report.bytes), '%PDF-1.4 test');
  });
  test('XLSM is saved as binary with correct extension', () async {
    final report = await fetchQualityReport(MockClient((_) async => http.Response.bytes([80,75,3,4,0,255],200)),
      origin, '/quality/api/export/daily-xlsm', 'test');
    expect(report.name, 'MIELL_Report.xlsm');
    expect(report.bytes, [80,75,3,4,0,255]);
  });
  test('external URLs and non-export routes cannot receive credentials', () async {
    final client = MockClient((_) async { fail('Request must not be sent'); });
    for (final path in ['https://other.test/quality/api/export/pdf', '/api/me', '/quality/api/export/unknown']) {
      await expectLater(fetchQualityReport(client, origin, path, 'test'), throwsException);
    }
  });
  test('server errors and expired sessions are visible instead of saved', () async {
    for (final status in [401,403,500,302]) {
      await expectLater(fetchQualityReport(MockClient((_) async => http.Response('{"detail":"Export zlyhal"}',status)),
        origin, '/quality/api/export/pdf', 'test'), throwsException);
    }
  });
  test('HTML login response is not saved as a report', () async {
    await expectLater(fetchQualityReport(MockClient((_) async => http.Response('<html>Login</html>',200)),
      origin, '/quality/api/export/pdf', 'test'), throwsException);
  });
}
