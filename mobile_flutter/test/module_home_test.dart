import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:dochadzka_mobile/main.dart';

void main() {
  for (final role in ['employee', 'admin']) {
    testWidgets('$role can choose attendance or quality and log out', (tester) async {
      var loggedOut = false;
      await tester.pumpWidget(MaterialApp(home: ModuleHome(
        user: {'role': role, 'name': 'Test'},
        onLogout: () async { loggedOut = true; },
      )));
      expect(find.text('Dochádzka'), findsOneWidget);
      expect(find.text('Kvalita'), findsOneWidget);
      await tester.tap(find.byTooltip('Odhlásiť'));
      await tester.pump();
      expect(loggedOut, isTrue);
    });
  }
}
