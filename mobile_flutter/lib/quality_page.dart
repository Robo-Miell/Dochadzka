import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'barcode_page.dart';

/// Uses the existing employee session only on the configured server origin.
class QualityPage extends StatefulWidget {
  final String baseUrl;
  final String token;
  const QualityPage({super.key, required this.baseUrl, required this.token});

  @override
  State<QualityPage> createState() => _QualityPageState();
}

class _QualityPageState extends State<QualityPage> {
  late final WebViewController controller;
  late final Uri origin;
  bool authenticated = false;
  bool loading = true;
  String? error;
  bool scanning = false;

  Future<void> scanDelivery(JavaScriptMessage message) async {
    if (scanning || message.message != 'rDelivery') return;
    final url = Uri.tryParse(await controller.currentUrl() ?? '');
    if (url == null || url.scheme != origin.scheme || url.host != origin.host ||
        url.port != origin.port || !url.path.startsWith('/quality/')) {
      return;
    }
    if (!mounted) return;
    scanning = true;
    try {
      final value = await Navigator.push<String>(context,
        MaterialPageRoute(builder: (_) => const BarcodePage()));
      if (mounted) {
        await controller.runJavaScript(
          'window.miellBarcodeResult?.(${jsonEncode(value)});',
        );
      }
    } finally {
      scanning = false;
    }
  }

  @override
  void initState() {
    super.initState();
    origin = Uri.parse(widget.baseUrl);
    controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..addJavaScriptChannel('MiellScanner', onMessageReceived: scanDelivery)
      ..setNavigationDelegate(NavigationDelegate(
        onNavigationRequest: (request) {
          final uri = Uri.tryParse(request.url);
          if (uri == null || (uri.scheme != 'https' && uri.scheme != 'http') || uri.origin != origin.origin) {
            return NavigationDecision.prevent;
          }
          if (authenticated && request.isMainFrame && uri.path == '/') {
            if (mounted) Navigator.pop(context, uri.queryParameters['view'] != 'attendance');
            return NavigationDecision.prevent;
          }
          return NavigationDecision.navigate;
        },
        onPageStarted: (_) {
          if (mounted) setState(() { loading = true; error = null; });
        },
        onPageFinished: (url) async {
          final uri = Uri.parse(url);
          if (uri.origin != origin.origin) return;
          try {
            if (!authenticated && uri.path == '/health') {
              await controller.runJavaScript(
                'localStorage.clear(); localStorage.setItem("dochadzka_token", ${jsonEncode(widget.token)});',
              );
              authenticated = true;
              await controller.loadRequest(origin.resolve('/quality/'));
            } else if (mounted) {
              setState(() => loading = false);
            }
          } catch (_) {
            if (mounted) {
              setState(() {
                loading = false;
                error = 'Kvalitu sa nepodarilo načítať. Skús to znova.';
              });
            }
          }
        },
        onWebResourceError: (failure) {
          if (failure.isForMainFrame == true && mounted) {
            setState(() {
              loading = false;
              error = 'Server nie je dostupný. Skontroluj internet a skús to znova.';
            });
          }
        },
      ));
    controller.loadRequest(origin.resolve('/health'));
  }

  @override
  void dispose() {
    controller.clearLocalStorage().catchError((Object _) {});
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Kvalita'), actions: [
      IconButton(tooltip: 'Obnoviť', icon: const Icon(Icons.refresh), onPressed: () {
        authenticated = false;
        controller.loadRequest(origin.resolve('/health'));
      }),
    ]),
    body: SafeArea(child: Stack(children: [
      WebViewWidget(controller: controller),
      if (loading) const Positioned.fill(
        child: ColoredBox(color: Colors.white, child: Center(child: CircularProgressIndicator())),
      ),
      if (error != null) Positioned.fill(child: ColoredBox(
        color: Colors.white,
        child: Center(child: Padding(padding: const EdgeInsets.all(24), child: Text(error!))),
      )),
    ])),
  );
}
