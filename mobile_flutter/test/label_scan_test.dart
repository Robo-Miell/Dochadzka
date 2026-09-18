import 'package:flutter_test/flutter_test.dart';
import 'package:dochadzka_mobile/label_scan.dart';

void main() {
  test('actual label preserves punctuation and ignores other prefixes', () {
    final scan = LabelScan();
    for (var i = 0; i < 3; i++) {
      scan.addFrame(['N8188175', 'Q28', 'P51.02201-0171', 'S574413751', 'V01026080', 'H8188175']);
    }
    expect(scan.ready, isTrue);
    expect(scan.selected('P'), '51.02201-0171');
    expect(scan.selected('S'), '574413751');
    expect(scan.selected('Q'), '28');
    expect(scan.result.length, 3);
  });
  test('one bad camera reading does not create a conflict', () {
    final scan = LabelScan();
    scan.addFrame(['P51202201-0171']);
    for (var i = 0; i < 3; i++) { scan.addFrame(['P51.02201-0171']); }
    expect(scan.ready, isTrue);
    expect(scan.selected('P'), '51.02201-0171');
  });
  test('duplicates within one frame are not confirmations', () {
    final scan = LabelScan();
    scan.addFrame(['Q28', 'Q28', 'Q28']);
    expect(scan.ready, isFalse);
  });
  test('confirmed conflict requires a choice, which resolves it', () {
    final scan = LabelScan();
    for (var i = 0; i < 3; i++) { scan.addFrame(['Q28', 'Q29']); }
    expect(scan.ready, isFalse);
    scan.choices['Q'] = '28';
    expect(scan.ready, isTrue);
    expect(scan.result, ['Q28']);
    scan.clear();
    expect(scan.ready, isFalse);
    expect(scan.choices, isEmpty);
  });
}
