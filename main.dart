import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:intl/intl.dart';
import 'package:shared_preferences/shared_preferences.dart';

const apiBase = String.fromEnvironment(
  'API_URL',
  defaultValue: 'http://10.0.2.2:8000',
);

void main() => runApp(const AttendanceApp());

class AttendanceApp extends StatelessWidget {
  const AttendanceApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Dochádzka',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(useMaterial3: true, colorSchemeSeed: Colors.blue),
      home: const RootPage(),
    );
  }
}

class Api {
  String? token;

  Future<dynamic> request(
    String path, {
    String method = 'GET',
    Object? body,
  }) async {
    final uri = Uri.parse('$apiBase$path');
    final headers = <String, String>{'Content-Type': 'application/json'};
    if (token != null) headers['Authorization'] = 'Bearer $token';

    late http.Response r;
    final payload = body == null ? null : jsonEncode(body);

    switch (method) {
      case 'POST':
        r = await http.post(uri, headers: headers, body: payload);
        break;
      case 'PATCH':
        r = await http.patch(uri, headers: headers, body: payload);
        break;
      case 'DELETE':
        r = await http.delete(uri, headers: headers);
        break;
      default:
        r = await http.get(uri, headers: headers);
    }

    if (r.statusCode >= 400) {
      String message = 'Chyba ${r.statusCode}';
      try {
        final parsed = jsonDecode(r.body);
        message = parsed['detail']?.toString() ?? message;
      } catch (_) {}
      throw Exception(message);
    }
    if (r.body.isEmpty) return null;
    return jsonDecode(utf8.decode(r.bodyBytes));
  }
}

final api = Api();

class RootPage extends StatefulWidget {
  const RootPage({super.key});
  @override
  State<RootPage> createState() => _RootPageState();
}

class _RootPageState extends State<RootPage> {
  bool loading = true;
  Map<String, dynamic>? user;

  @override
  void initState() {
    super.initState();
    restore();
  }

  Future<void> restore() async {
    final p = await SharedPreferences.getInstance();
    api.token = p.getString('token');
    if (api.token != null) {
      try {
        user = Map<String, dynamic>.from(await api.request('/api/me'));
      } catch (_) {
        api.token = null;
        await p.remove('token');
      }
    }
    if (mounted) setState(() => loading = false);
  }

  void loggedIn(Map<String, dynamic> u) {
    setState(() => user = u);
  }

  Future<void> logout() async {
    final p = await SharedPreferences.getInstance();
    await p.remove('token');
    api.token = null;
    setState(() => user = null);
  }

  @override
  Widget build(BuildContext context) {
    if (loading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (user == null) return LoginPage(onLogin: loggedIn);

    if (user!['role'] == 'admin') {
      return AdminInfoPage(user: user!, onLogout: logout);
    }
    return EmployeeHome(user: user!, onLogout: logout);
  }
}

class LoginPage extends StatefulWidget {
  final void Function(Map<String, dynamic>) onLogin;
  const LoginPage({super.key, required this.onLogin});
  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final login = TextEditingController();
  final password = TextEditingController();
  bool busy = false;
  String? error;

  Future<void> submit() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final data = Map<String, dynamic>.from(await api.request(
        '/api/auth/login',
        method: 'POST',
        body: {'login': login.text.trim(), 'password': password.text},
      ));
      api.token = data['access_token'];
      final p = await SharedPreferences.getInstance();
      await p.setString('token', api.token!);
      widget.onLogin(Map<String, dynamic>.from(data['user']));
    } catch (e) {
      setState(() => error = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 430),
            child: ListView(
              padding: const EdgeInsets.all(24),
              shrinkWrap: true,
              children: [
                const Icon(Icons.badge_outlined, size: 64),
                const SizedBox(height: 16),
                Text('Dochádzka', style: Theme.of(context).textTheme.headlineMedium),
                const SizedBox(height: 6),
                const Text('Prihlás sa svojím firemným účtom.'),
                const SizedBox(height: 24),
                TextField(
                  controller: login,
                  decoration: const InputDecoration(
                    labelText: 'Login',
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: password,
                  obscureText: true,
                  onSubmitted: (_) => submit(),
                  decoration: const InputDecoration(
                    labelText: 'Heslo',
                    border: OutlineInputBorder(),
                  ),
                ),
                if (error != null) ...[
                  const SizedBox(height: 12),
                  Text(error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                ],
                const SizedBox(height: 16),
                FilledButton(
                  onPressed: busy ? null : submit,
                  child: busy
                      ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Text('Prihlásiť'),
                ),
                const SizedBox(height: 12),
                Text(
                  'Server: $apiBase',
                  style: Theme.of(context).textTheme.bodySmall,
                  textAlign: TextAlign.center,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class EmployeeHome extends StatefulWidget {
  final Map<String, dynamic> user;
  final Future<void> Function() onLogout;
  const EmployeeHome({super.key, required this.user, required this.onLogout});

  @override
  State<EmployeeHome> createState() => _EmployeeHomeState();
}

class _EmployeeHomeState extends State<EmployeeHome> {
  List<dynamic> attendance = [];
  List<dynamic> locations = [];
  bool loading = true;
  String? error;

  @override
  void initState() {
    super.initState();
    refresh();
  }

  Future<void> refresh() async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final results = await Future.wait([
        api.request('/api/attendance'),
        api.request('/api/locations'),
      ]);
      attendance = List<dynamic>.from(results[0]);
      locations = List<dynamic>.from(results[1]);
    } catch (e) {
      error = e.toString().replaceFirst('Exception: ', '');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  double get approvedHours {
    double total = 0;
    for (final a in attendance) {
      if (a['status'] == 'approved') {
        total += (a['hours'] as num?)?.toDouble() ?? 0;
      }
    }
    return total;
  }

  int get pendingCount =>
      attendance.where((x) => x['status'] == 'pending').length;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Moja dochádzka'),
        actions: [
          IconButton(onPressed: refresh, icon: const Icon(Icons.refresh)),
          IconButton(onPressed: widget.onLogout, icon: const Icon(Icons.logout)),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: locations.isEmpty
            ? null
            : () async {
                final saved = await Navigator.push<bool>(
                  context,
                  MaterialPageRoute(
                    builder: (_) => AddAttendancePage(
                      locations: locations,
                      defaultLocationId: widget.user['location_id'],
                    ),
                  ),
                );
                if (saved == true) refresh();
              },
        icon: const Icon(Icons.add),
        label: const Text('Pridať'),
      ),
      body: RefreshIndicator(
        onRefresh: refresh,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text(
              widget.user['name'] ?? '',
              style: Theme.of(context).textTheme.headlineSmall,
            ),
            Text(
              'Osobné číslo: ${widget.user['personal_number']} • ${widget.user['location_name'] ?? ''}',
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: _Metric(
                    title: 'Schválené hodiny',
                    value: '${approvedHours.toStringAsFixed(1)} h',
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: _Metric(
                    title: 'Čaká',
                    value: '$pendingCount',
                  ),
                ),
              ],
            ),
            const SizedBox(height: 18),
            if (loading) const Center(child: CircularProgressIndicator()),
            if (error != null)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: Text(error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ),
            ...attendance.map((a) => _AttendanceCard(a: Map<String, dynamic>.from(a))),
            const SizedBox(height: 90),
          ],
        ),
      ),
    );
  }
}

class _Metric extends StatelessWidget {
  final String title;
  final String value;
  const _Metric({required this.title, required this.value});
  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 6),
            Text(value, style: Theme.of(context).textTheme.headlineSmall),
          ],
        ),
      ),
    );
  }
}

class _AttendanceCard extends StatelessWidget {
  final Map<String, dynamic> a;
  const _AttendanceCard({required this.a});

  String status(String s) {
    switch (s) {
      case 'approved':
        return 'Schválené';
      case 'rejected':
        return 'Zamietnuté';
      default:
        return 'Čaká na schválenie';
    }
  }

  @override
  Widget build(BuildContext context) {
    final from = a['time_from'];
    final to = a['time_to'];
    final time = from == null ? '' : '$from${to == null ? '' : ' – $to'}';
    return Card(
      child: ListTile(
        title: Text('${a['work_date']} • ${a['type']}'),
        subtitle: Text(
          '${a['location_name']}\n'
          '${time.isEmpty ? '' : '$time • '}${(a['hours'] as num).toStringAsFixed(2)} h\n'
          '${status(a['status'])}${(a['note'] ?? '').toString().isEmpty ? '' : ' • ${a['note']}'}',
        ),
        isThreeLine: true,
      ),
    );
  }
}

class AddAttendancePage extends StatefulWidget {
  final List<dynamic> locations;
  final dynamic defaultLocationId;
  const AddAttendancePage({
    super.key,
    required this.locations,
    required this.defaultLocationId,
  });

  @override
  State<AddAttendancePage> createState() => _AddAttendancePageState();
}

class _AddAttendancePageState extends State<AddAttendancePage> {
  DateTime day = DateTime.now();
  String type = 'Práca';
  int? locationId;
  TimeOfDay from = const TimeOfDay(hour: 8, minute: 0);
  TimeOfDay to = const TimeOfDay(hour: 16, minute: 0);
  final breakCtrl = TextEditingController(text: '30');
  final noteCtrl = TextEditingController();
  bool busy = false;
  String? error;

  final types = const [
    'Práca',
    'Dovolenka',
    'Lekár',
    'PN',
    'OČR',
    'Náhradné voľno',
    'Iné',
  ];

  @override
  void initState() {
    super.initState();
    locationId = widget.defaultLocationId as int?;
    if (locationId == null && widget.locations.isNotEmpty) {
      locationId = widget.locations.first['id'] as int;
    }
  }

  String fmt(TimeOfDay t) =>
      '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

  Future<void> save() async {
    if (locationId == null) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await api.request(
        '/api/attendance',
        method: 'POST',
        body: {
          'work_date': DateFormat('yyyy-MM-dd').format(day),
          'location_id': locationId,
          'type': type,
          'time_from': (type == 'Práca' || type == 'Lekár') ? fmt(from) : null,
          'time_to': (type == 'Práca' || type == 'Lekár') ? fmt(to) : null,
          'break_minutes': type == 'Práca' ? int.tryParse(breakCtrl.text) ?? 0 : 0,
          'note': noteCtrl.text.trim(),
        },
      );
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      setState(() => error = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final usesTime = type == 'Práca' || type == 'Lekár';
    return Scaffold(
      appBar: AppBar(title: const Text('Nový záznam')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Dátum'),
            subtitle: Text(DateFormat('dd.MM.yyyy').format(day)),
            trailing: const Icon(Icons.calendar_month),
            onTap: () async {
              final d = await showDatePicker(
                context: context,
                firstDate: DateTime(2020),
                lastDate: DateTime(2035),
                initialDate: day,
              );
              if (d != null) setState(() => day = d);
            },
          ),
          DropdownButtonFormField<String>(
            value: type,
            decoration: const InputDecoration(labelText: 'Typ', border: OutlineInputBorder()),
            items: types.map((x) => DropdownMenuItem(value: x, child: Text(x))).toList(),
            onChanged: (v) => setState(() => type = v!),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<int>(
            value: locationId,
            decoration: const InputDecoration(labelText: 'Prevádzka', border: OutlineInputBorder()),
            items: widget.locations
                .map<DropdownMenuItem<int>>(
                  (x) => DropdownMenuItem<int>(
                    value: x['id'] as int,
                    child: Text(x['name'].toString()),
                  ),
                )
                .toList(),
            onChanged: (v) => setState(() => locationId = v),
          ),
          if (usesTime) ...[
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () async {
                      final t = await showTimePicker(context: context, initialTime: from);
                      if (t != null) setState(() => from = t);
                    },
                    child: Text('Od ${fmt(from)}'),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: OutlinedButton(
                    onPressed: () async {
                      final t = await showTimePicker(context: context, initialTime: to);
                      if (t != null) setState(() => to = t);
                    },
                    child: Text('Do ${fmt(to)}'),
                  ),
                ),
              ],
            ),
          ],
          if (type == 'Práca') ...[
            const SizedBox(height: 12),
            TextField(
              controller: breakCtrl,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                labelText: 'Prestávka v minútach',
                border: OutlineInputBorder(),
              ),
            ),
          ],
          const SizedBox(height: 12),
          TextField(
            controller: noteCtrl,
            decoration: const InputDecoration(
              labelText: 'Poznámka',
              border: OutlineInputBorder(),
            ),
          ),
          if (error != null) ...[
            const SizedBox(height: 12),
            Text(error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
          const SizedBox(height: 18),
          FilledButton(
            onPressed: busy ? null : save,
            child: busy ? const CircularProgressIndicator() : const Text('Odoslať na schválenie'),
          ),
        ],
      ),
    );
  }
}

class AdminInfoPage extends StatelessWidget {
  final Map<String, dynamic> user;
  final Future<void> Function() onLogout;
  const AdminInfoPage({super.key, required this.user, required this.onLogout});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Dochádzka – Admin'),
        actions: [IconButton(onPressed: onLogout, icon: const Icon(Icons.logout))],
      ),
      body: Padding(
        padding: const EdgeInsets.all(20),
        child: Card(
          child: Padding(
            padding: const EdgeInsets.all(18),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Prihlásený: ${user['name']}', style: Theme.of(context).textTheme.titleLarge),
                const SizedBox(height: 10),
                const Text(
                  'Kompletná administrácia je v tejto verzii určená pre webový prehliadač. '
                  'Mobilná aplikácia je optimalizovaná najmä pre zamestnancov.',
                ),
                const SizedBox(height: 10),
                SelectableText('Admin web: $apiBase/admin'),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
