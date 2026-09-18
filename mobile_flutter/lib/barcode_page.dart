import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'label_scan.dart';

class BarcodePage extends StatefulWidget {
  const BarcodePage({super.key});
  @override
  State<BarcodePage> createState() => _BarcodePageState();
}

class _BarcodePageState extends State<BarcodePage> {
  final controller = MobileScannerController(detectionSpeed: DetectionSpeed.normal);
  final label = LabelScan();

  @override
  void dispose() { controller.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Skenovať etiketu')),
    body: SafeArea(child: Column(children: [
      const Padding(padding: EdgeInsets.all(12),
        child: Text('Podrž kameru na jednej etikete. Hodnoty overujem opakovaným čítaním.')),
      Expanded(child: MobileScanner(
        controller: controller,
        errorBuilder: (context, error) => const Center(child: Padding(
          padding: EdgeInsets.all(24),
          child: Text('Povoľ aplikácii prístup ku kamere alebo zadaj hodnoty ručne.'),
        )),
        onDetect: (capture) {
          if (mounted) {
            setState(() => label.addFrame(capture.barcodes.map((b) => b.rawValue).whereType<String>()));
          }
        },
      )),
      ConstrainedBox(constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(context).height * .4),
        child: SingleChildScrollView(padding: const EdgeInsets.all(12), child: Column(children: [
          for (final entry in {'P':'Číslo dielu', 'S':'Dodací list', 'Q':'Checked'}.entries)
            Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Text('${entry.value}: ${label.selected(entry.key) ?? "—"}'),
              if ((label.candidates[entry.key]?.length ?? 0) > 1) ...[
                const Text('Zachytené rôzne hodnoty. Vyber správnu podľa etikety:', style: TextStyle(color: Colors.deepOrange)),
                Wrap(spacing: 8, children: [
                  for (final value in label.candidates[entry.key]!)
                    ChoiceChip(label: Text(value), selected: label.selected(entry.key) == value,
                      onSelected: (_) => setState(() => label.choices[entry.key] = value)),
                ]),
              ],
            ]),
        ])),
      ),
      FilledButton.icon(onPressed: label.ready ? () => Navigator.pop(context, label.result) : null,
        icon: const Icon(Icons.check), label: const Text('Použiť hodnoty')),
      TextButton(onPressed: () => setState(label.clear), child: const Text('Vymazať načítané kódy')),
      TextButton(onPressed: () => Navigator.pop(context), child: const Text('Zrušiť')),
    ])),
  );
}
