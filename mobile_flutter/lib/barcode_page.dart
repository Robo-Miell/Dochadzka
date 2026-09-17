import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

class BarcodePage extends StatefulWidget {
  const BarcodePage({super.key});
  @override
  State<BarcodePage> createState() => _BarcodePageState();
}

class _BarcodePageState extends State<BarcodePage> {
  final controller = MobileScannerController();
  final codes = <String>{};
  final fields = <String, String>{};
  final conflicts = <String>{};

  void detect(BarcodeCapture capture) {
    var changed = false;
    for (final barcode in capture.barcodes) {
      final raw = barcode.rawValue;
      if (raw == null) continue;
      for (final line in raw.split(RegExp(r'[\r\n\t\x1d\x1e;]+'))) {
        final match = RegExp(r'^([PSQ])(.+)$').firstMatch(line.trim());
        if (match == null || !codes.add(line.trim())) continue;
        changed = true;
        final prefix = match.group(1)!;
        final value = match.group(2)!;
        if (fields.containsKey(prefix) && fields[prefix] != value) {
          conflicts.add(prefix);
        }
        fields[prefix] = value;
      }
    }
    if (changed && mounted) setState(() {});
  }

  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Skenovať etiketu')),
    body: SafeArea(child: Column(children: [
      const Padding(padding: EdgeInsets.all(12),
        child: Text('Nasnímaj kódy jednej etikety. Môžeš ich snímať postupne.')),
      Expanded(child: MobileScanner(
        controller: controller,
        errorBuilder: (context, error) => const Center(child: Padding(
          padding: EdgeInsets.all(24),
          child: Text('Fotoaparát nie je dostupný. Povoľ prístup ku kamere v nastaveniach telefónu alebo zadaj hodnoty ručne.'),
        )),
        onDetect: detect,
      )),
      Padding(padding: const EdgeInsets.all(12), child: Column(children: [
        for (final entry in {'P':'Číslo dielu', 'S':'Dodací list', 'Q':'Checked'}.entries)
          Text('${entry.value}: ${fields[entry.key] ?? "—"}', maxLines: 2, overflow: TextOverflow.ellipsis),
        if (conflicts.isNotEmpty)
          const Text('Rôzne hodnoty rovnakého prefixu. Vymaž načítané kódy a nasnímaj jednu etiketu.',
            style: TextStyle(color: Colors.red)),
        FilledButton.icon(
          onPressed: codes.isEmpty || conflicts.isNotEmpty ? null : () => Navigator.pop(context, codes.toList()),
          icon: const Icon(Icons.check), label: const Text('Použiť hodnoty')),
        TextButton(onPressed: () => setState(() { codes.clear(); fields.clear(); conflicts.clear(); }),
          child: const Text('Vymazať načítané kódy')),
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Zrušiť')),
      ])),
    ])),
  );
}
