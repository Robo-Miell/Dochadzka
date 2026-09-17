import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

class BarcodePage extends StatefulWidget {
  const BarcodePage({super.key});

  @override
  State<BarcodePage> createState() => _BarcodePageState();
}

class _BarcodePageState extends State<BarcodePage> {
  final controller = MobileScannerController();
  String? value;

  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Skenovať dodací list')),
    body: SafeArea(child: Column(children: [
      const Padding(padding: EdgeInsets.all(16),
        child: Text('Namier fotoaparát na jeden čiarový alebo QR kód.')),
      Expanded(child: value == null ? MobileScanner(
        controller: controller,
        errorBuilder: (context, error) => const Center(child: Padding(
          padding: EdgeInsets.all(24),
          child: Text('Fotoaparát nie je dostupný. Povoľ aplikácii prístup ku kamere v nastaveniach telefónu. Číslo môžeš zadať aj ručne.'),
        )),
        onDetect: (capture) {
          if (value != null) return;
          final codes = capture.barcodes.map((b) => b.rawValue)
            .whereType<String>().where((s) => s.isNotEmpty).toSet();
          if (codes.length != 1) return;
          setState(() => value = codes.single);
          controller.stop();
        },
      ) : Center(child: SingleChildScrollView(padding: const EdgeInsets.all(24),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const Text('Načítané číslo dodacieho listu:'),
          const SizedBox(height: 16),
          SelectableText(value!, style: Theme.of(context).textTheme.headlineSmall),
        ]),
      ))),
      if (value != null) Padding(padding: const EdgeInsets.all(16), child: Column(children: [
        FilledButton.icon(onPressed: () => Navigator.pop(context, value),
          icon: const Icon(Icons.check), label: const Text('Použiť číslo')),
        TextButton(onPressed: () { setState(() => value = null); },
          child: const Text('Skenovať znova')),
      ])),
      TextButton(onPressed: () => Navigator.pop(context), child: const Text('Zrušiť')),
    ])),
  );
}
