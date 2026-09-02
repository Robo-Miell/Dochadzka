import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

const apiBase = String.fromEnvironment(
  'API_URL',
  defaultValue: 'https://dochadzka1.onrender.com',
);

const brandGreen = Color(0xFF4DBB43);
const skMonths = <String>[
  'Január',
  'Február',
  'Marec',
  'Apríl',
  'Máj',
  'Jún',
  'Júl',
  'August',
  'September',
  'Október',
  'November',
  'December',
];

String isoDate(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

String displayDate(DateTime d) =>
    '${d.day.toString().padLeft(2, '0')}.${d.month.toString().padLeft(2, '0')}.${d.year}';

String displayIsoDate(String value) {
  final d = DateTime.tryParse(value);
  return d == null ? value : displayDate(d);
}

String monthTitle(DateTime d) => '${skMonths[d.month - 1]} ${d.year}';
DateTime monthStart(DateTime d) => DateTime(d.year, d.month, 1);
DateTime monthEnd(DateTime d) => DateTime(d.year, d.month + 1, 0);

TimeOfDay parseTime(String? value, TimeOfDay fallback) {
  if (value == null) return fallback;
  final parts = value.split(':');
  if (parts.length != 2) return fallback;
  final h = int.tryParse(parts[0]);
  final m = int.tryParse(parts[1]);
  if (h == null || m == null) return fallback;
  return TimeOfDay(hour: h, minute: m);
}

String formatTime(TimeOfDay t) =>
    '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

void main() => runApp(const AttendanceApp());

class AttendanceApp extends StatelessWidget {
  const AttendanceApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'MIELL Dochádzka',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(seedColor: brandGreen),
        inputDecorationTheme: const InputDecorationTheme(
          border: OutlineInputBorder(),
        ),
      ),
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
    final payload = body == null ? null : jsonEncode(body);

    late http.Response response;
    switch (method) {
      case 'POST':
        response = await http.post(uri, headers: headers, body: payload);
        break;
      case 'PATCH':
        response = await http.patch(uri, headers: headers, body: payload);
        break;
      case 'DELETE':
        response = await http.delete(uri, headers: headers);
        break;
      default:
        response = await http.get(uri, headers: headers);
    }

    if (response.statusCode >= 400) {
      String message = 'Chyba ${response.statusCode}';
      try {
        final parsed = jsonDecode(utf8.decode(response.bodyBytes));
        message = parsed['detail']?.toString() ?? message;
      } catch (_) {}
      throw Exception(message);
    }
    if (response.bodyBytes.isEmpty) return null;
    return jsonDecode(utf8.decode(response.bodyBytes));
  }
}

final api = Api();

String cleanError(Object e) => e.toString().replaceFirst('Exception: ', '');

Future<bool> confirmDialog(
  BuildContext context, {
  required String title,
  required String text,
  String confirmText = 'Odstrániť',
}) async {
  return await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: Text(title),
          content: Text(text),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Zrušiť'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: Text(confirmText),
            ),
          ],
        ),
      ) ??
      false;
}

void showError(BuildContext context, Object error) {
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(content: Text(cleanError(error))),
  );
}

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
    final prefs = await SharedPreferences.getInstance();
    api.token = prefs.getString('token');
    if (api.token != null) {
      try {
        user = Map<String, dynamic>.from(await api.request('/api/me'));
      } catch (_) {
        api.token = null;
        await prefs.remove('token');
      }
    }
    if (mounted) setState(() => loading = false);
  }

  void loggedIn(Map<String, dynamic> value) {
    setState(() => user = value);
  }

  Future<void> logout() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('token');
    api.token = null;
    if (mounted) setState(() => user = null);
  }

  @override
  Widget build(BuildContext context) {
    if (loading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (user == null) return LoginPage(onLogin: loggedIn);
    if (user!['role'] == 'admin') {
      return AdminHome(user: user!, onLogout: logout);
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

  @override
  void dispose() {
    login.dispose();
    password.dispose();
    super.dispose();
  }

  Future<void> submit() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final data = Map<String, dynamic>.from(
        await api.request(
          '/api/auth/login',
          method: 'POST',
          body: {'login': login.text.trim(), 'password': password.text},
        ),
      );
      api.token = data['access_token']?.toString();
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('token', api.token!);
      widget.onLogin(Map<String, dynamic>.from(data['user']));
    } catch (e) {
      if (mounted) setState(() => error = cleanError(e));
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
                Image.asset(
                  'assets/miell_quality.png',
                  height: 125,
                  fit: BoxFit.contain,
                ),
                const SizedBox(height: 20),
                Text(
                  'Dochádzka',
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.headlineMedium,
                ),
                const SizedBox(height: 6),
                const Text(
                  'Prihlás sa svojím firemným účtom.',
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 24),
                TextField(
                  controller: login,
                  textInputAction: TextInputAction.next,
                  decoration: const InputDecoration(labelText: 'Login'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: password,
                  obscureText: true,
                  onSubmitted: (_) => submit(),
                  decoration: const InputDecoration(labelText: 'Heslo'),
                ),
                if (error != null) ...[
                  const SizedBox(height: 12),
                  Text(
                    error!,
                    style: TextStyle(color: Theme.of(context).colorScheme.error),
                  ),
                ],
                const SizedBox(height: 16),
                FilledButton(
                  onPressed: busy ? null : submit,
                  child: busy
                      ? const SizedBox(
                          width: 22,
                          height: 22,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Text('Prihlásiť'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class BrandAppTitle extends StatelessWidget {
  final String title;
  const BrandAppTitle(this.title, {super.key});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Image.asset(
          'assets/miell_quality.png',
          width: 92,
          height: 36,
          fit: BoxFit.contain,
        ),
        const SizedBox(width: 10),
        Flexible(child: Text(title)),
      ],
    );
  }
}

class MonthSelector extends StatelessWidget {
  final DateTime month;
  final VoidCallback onPrevious;
  final VoidCallback onNext;
  final VoidCallback onPick;
  final VoidCallback? onCurrent;

  const MonthSelector({
    super.key,
    required this.month,
    required this.onPrevious,
    required this.onNext,
    required this.onPick,
    this.onCurrent,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
        child: Row(
          children: [
            IconButton(
              tooltip: 'Predchádzajúci mesiac',
              onPressed: onPrevious,
              icon: const Icon(Icons.chevron_left),
            ),
            Expanded(
              child: InkWell(
                borderRadius: BorderRadius.circular(10),
                onTap: onPick,
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 10),
                  child: Column(
                    children: [
                      Text(
                        monthTitle(month),
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      const Text(
                        'Ťukni pre výber mesiaca',
                        style: TextStyle(fontSize: 11),
                      ),
                    ],
                  ),
                ),
              ),
            ),
            IconButton(
              tooltip: 'Nasledujúci mesiac',
              onPressed: onNext,
              icon: const Icon(Icons.chevron_right),
            ),
            if (onCurrent != null)
              IconButton(
                tooltip: 'Aktuálny mesiac',
                onPressed: onCurrent,
                icon: const Icon(Icons.today),
              ),
          ],
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
  DateTime selectedMonth = monthStart(DateTime.now());

  @override
  void initState() {
    super.initState();
    refresh();
  }

  String get attendancePath =>
      '/api/attendance?date_from=${isoDate(monthStart(selectedMonth))}&date_to=${isoDate(monthEnd(selectedMonth))}';

  Future<void> refresh() async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final results = await Future.wait([
        api.request(attendancePath),
        api.request('/api/locations'),
      ]);
      attendance = List<dynamic>.from(results[0]);
      locations = List<dynamic>.from(results[1]);
    } catch (e) {
      error = cleanError(e);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> changeMonth(int delta) async {
    selectedMonth = DateTime(selectedMonth.year, selectedMonth.month + delta, 1);
    await refresh();
  }

  Future<void> pickMonth() async {
    final picked = await showDatePicker(
      context: context,
      firstDate: DateTime(2020, 1, 1),
      lastDate: DateTime(2035, 12, 31),
      initialDate: selectedMonth,
      helpText: 'Vyber deň v požadovanom mesiaci',
    );
    if (picked != null) {
      selectedMonth = DateTime(picked.year, picked.month, 1);
      await refresh();
    }
  }

  double get approvedHours {
    double total = 0;
    for (final item in attendance) {
      if (item['status'] == 'approved') {
        total += (item['hours'] as num?)?.toDouble() ?? 0;
      }
    }
    return total;
  }

  int get pendingCount =>
      attendance.where((item) => item['status'] == 'pending').length;

  Future<void> deletePending(Map<String, dynamic> item) async {
    final yes = await confirmDialog(
      context,
      title: 'Odstrániť záznam?',
      text: '${displayIsoDate(item['work_date'].toString())} – ${item['type']}',
    );
    if (!yes) return;
    try {
      await api.request('/api/attendance/${item['id']}', method: 'DELETE');
      await refresh();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const BrandAppTitle('Moja dochádzka'),
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
                if (saved == true) await refresh();
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
              widget.user['name']?.toString() ?? '',
              style: Theme.of(context).textTheme.headlineSmall,
            ),
            Text(
              'Osobné číslo: ${widget.user['personal_number']} • ${widget.user['location_name'] ?? ''}',
            ),
            const SizedBox(height: 12),
            MonthSelector(
              month: selectedMonth,
              onPrevious: () => changeMonth(-1),
              onNext: () => changeMonth(1),
              onPick: pickMonth,
              onCurrent: () async {
                selectedMonth = monthStart(DateTime.now());
                await refresh();
              },
            ),
            const SizedBox(height: 10),
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
                  child: _Metric(title: 'Čaká', value: '$pendingCount'),
                ),
              ],
            ),
            const SizedBox(height: 18),
            if (loading) const Center(child: CircularProgressIndicator()),
            if (error != null)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: Text(
                  error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ),
            if (!loading && error == null && attendance.isEmpty)
              const Padding(
                padding: EdgeInsets.all(24),
                child: Center(child: Text('V tomto mesiaci nie sú žiadne záznamy.')),
              ),
            ...attendance.map(
              (item) => AttendanceCard(
                item: Map<String, dynamic>.from(item),
                onDelete: item['status'] == 'pending'
                    ? () => deletePending(Map<String, dynamic>.from(item))
                    : null,
              ),
            ),
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

class AttendanceCard extends StatelessWidget {
  final Map<String, dynamic> item;
  final VoidCallback? onTap;
  final VoidCallback? onDelete;
  const AttendanceCard({
    super.key,
    required this.item,
    this.onTap,
    this.onDelete,
  });

  String statusText(String value) {
    switch (value) {
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
    final from = item['time_from'];
    final to = item['time_to'];
    final time = from == null ? '' : '$from${to == null ? '' : ' – $to'}';
    final hours = (item['hours'] as num?)?.toDouble() ?? 0;
    final note = (item['note'] ?? '').toString();

    return Card(
      child: ListTile(
        onTap: onTap,
        title: Text('${displayIsoDate(item['work_date'].toString())} • ${item['type']}'),
        subtitle: Text(
          '${item['location_name'] ?? ''}\n'
          '${time.isEmpty ? '' : '$time • '}${hours.toStringAsFixed(2)} h\n'
          '${statusText(item['status']?.toString() ?? 'pending')}${note.isEmpty ? '' : ' • $note'}',
        ),
        isThreeLine: true,
        trailing: onDelete == null
            ? (onTap == null ? null : const Icon(Icons.edit_outlined))
            : IconButton(
                tooltip: 'Odstrániť čakajúci záznam',
                onPressed: onDelete,
                icon: const Icon(Icons.delete_outline),
              ),
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

  List<dynamic> shifts = [];
  int? selectedShiftId;
  bool customWorkTime = true;
  bool loadingShifts = false;

  static const types = [
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
    loadShifts();
  }

  @override
  void dispose() {
    breakCtrl.dispose();
    noteCtrl.dispose();
    super.dispose();
  }

  Future<void> loadShifts() async {
    final loc = locationId;
    if (loc == null) {
      if (mounted) {
        setState(() {
          shifts = [];
          selectedShiftId = null;
          customWorkTime = true;
        });
      }
      return;
    }
    if (mounted) setState(() => loadingShifts = true);
    try {
      final data = await api.request('/api/shifts?location_id=$loc');
      final items = List<dynamic>.from(data as List);
      if (!mounted) return;
      setState(() {
        shifts = items;
        if (items.isEmpty) {
          selectedShiftId = null;
          customWorkTime = true;
        } else {
          customWorkTime = false;
          selectedShiftId = items.first['id'] as int;
          from = parseTime(items.first['time_from']?.toString(), from);
          to = parseTime(items.first['time_to']?.toString(), to);
        }
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        shifts = [];
        selectedShiftId = null;
        customWorkTime = true;
      });
    } finally {
      if (mounted) setState(() => loadingShifts = false);
    }
  }

  void applyShift(int? id) {
    if (id == null) return;
    final item = shifts.cast<dynamic?>().firstWhere(
          (x) => x?['id'] == id,
          orElse: () => null,
        );
    if (item == null) return;
    setState(() {
      selectedShiftId = id;
      from = parseTime(item['time_from']?.toString(), from);
      to = parseTime(item['time_to']?.toString(), to);
    });
  }

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
          'work_date': isoDate(day),
          'location_id': locationId,
          'type': type,
          'time_from': (type == 'Práca' || type == 'Lekár') ? formatTime(from) : null,
          'time_to': (type == 'Práca' || type == 'Lekár') ? formatTime(to) : null,
          'break_minutes': type == 'Práca' ? int.tryParse(breakCtrl.text) ?? 0 : 0,
          'note': noteCtrl.text.trim(),
        },
      );
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) setState(() => error = cleanError(e));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final showManualTime = type == 'Lekár' ||
        (type == 'Práca' && (customWorkTime || shifts.isEmpty));
    return Scaffold(
      appBar: AppBar(title: const BrandAppTitle('Nový záznam')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Dátum'),
            subtitle: Text(displayDate(day)),
            trailing: const Icon(Icons.calendar_month),
            onTap: () async {
              final picked = await showDatePicker(
                context: context,
                firstDate: DateTime(2020),
                lastDate: DateTime(2035, 12, 31),
                initialDate: day,
              );
              if (picked != null) setState(() => day = picked);
            },
          ),
          DropdownButtonFormField<String>(
            initialValue: type,
            decoration: const InputDecoration(labelText: 'Typ'),
            items: types
                .map((value) => DropdownMenuItem(value: value, child: Text(value)))
                .toList(),
            onChanged: (value) => setState(() => type = value!),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<int>(
            initialValue: locationId,
            decoration: const InputDecoration(labelText: 'Prevádzka'),
            items: widget.locations
                .map<DropdownMenuItem<int>>(
                  (item) => DropdownMenuItem<int>(
                    value: item['id'] as int,
                    child: Text(item['name'].toString()),
                  ),
                )
                .toList(),
            onChanged: (value) async {
              setState(() => locationId = value);
              await loadShifts();
            },
          ),
          if (type == 'Práca') ...[
            const SizedBox(height: 12),
            if (loadingShifts)
              const LinearProgressIndicator()
            else if (shifts.isNotEmpty) ...[
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Vlastný časový úsek'),
                subtitle: Text(
                  customWorkTime
                      ? 'Čas zadáš ručne.'
                      : 'Používa sa prednastavená zmena.',
                ),
                value: customWorkTime,
                onChanged: (value) {
                  setState(() => customWorkTime = value);
                  if (!value && selectedShiftId != null) {
                    applyShift(selectedShiftId);
                  }
                },
              ),
              if (!customWorkTime) ...[
                const SizedBox(height: 4),
                DropdownButtonFormField<int>(
                  key: ValueKey('shift-$selectedShiftId-${shifts.length}'),
                  initialValue: selectedShiftId,
                  decoration: const InputDecoration(labelText: 'Pracovná zmena'),
                  items: shifts
                      .map<DropdownMenuItem<int>>(
                        (item) => DropdownMenuItem<int>(
                          value: item['id'] as int,
                          child: Text(
                            '${item['name']}  ${item['time_from']} – ${item['time_to']}',
                          ),
                        ),
                      )
                      .toList(),
                  onChanged: applyShift,
                ),
              ],
            ] else
              const Card(
                child: Padding(
                  padding: EdgeInsets.all(12),
                  child: Text(
                    'Pre túto prevádzku nie sú prednastavené zmeny. Zadaj vlastný čas.',
                  ),
                ),
              ),
          ],
          if (showManualTime) ...[
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    icon: const Icon(Icons.login),
                    onPressed: () async {
                      final picked = await showTimePicker(context: context, initialTime: from);
                      if (picked != null) setState(() => from = picked);
                    },
                    label: Text('Od ${formatTime(from)}'),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: OutlinedButton.icon(
                    icon: const Icon(Icons.logout),
                    onPressed: () async {
                      final picked = await showTimePicker(context: context, initialTime: to);
                      if (picked != null) setState(() => to = picked);
                    },
                    label: Text('Do ${formatTime(to)}'),
                  ),
                ),
              ],
            ),
          ],
          if (type == 'Práca' && !showManualTime && selectedShiftId != null) ...[
            const SizedBox(height: 12),
            Card(
              child: ListTile(
                leading: const Icon(Icons.schedule),
                title: Text('Od ${formatTime(from)} do ${formatTime(to)}'),
                subtitle: const Text('Čas je prevzatý z vybranej zmeny.'),
              ),
            ),
          ],
          if (type == 'Práca') ...[
            const SizedBox(height: 12),
            TextField(
              controller: breakCtrl,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(labelText: 'Prestávka v minútach'),
            ),
          ],
          const SizedBox(height: 12),
          TextField(
            controller: noteCtrl,
            maxLines: 2,
            decoration: const InputDecoration(labelText: 'Poznámka'),
          ),
          if (error != null) ...[
            const SizedBox(height: 12),
            Text(error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
          const SizedBox(height: 18),
          FilledButton(
            onPressed: busy ? null : save,
            child: busy
                ? const SizedBox(
                    width: 22,
                    height: 22,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Text('Odoslať na schválenie'),
          ),
        ],
      ),
    );
  }
}

class AdminHome extends StatefulWidget {
  final Map<String, dynamic> user;
  final Future<void> Function() onLogout;
  const AdminHome({super.key, required this.user, required this.onLogout});

  @override
  State<AdminHome> createState() => _AdminHomeState();
}

class _AdminHomeState extends State<AdminHome> {
  int index = 0;
  bool loading = true;
  String? error;
  List<dynamic> users = [];
  List<dynamic> locations = [];
  List<dynamic> attendance = [];
  DateTime selectedMonth = monthStart(DateTime.now());

  @override
  void initState() {
    super.initState();
    refresh();
  }

  String get attendancePath =>
      '/api/attendance?date_from=${isoDate(monthStart(selectedMonth))}&date_to=${isoDate(monthEnd(selectedMonth))}';

  Future<void> refresh() async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final result = await Future.wait([
        api.request('/api/users'),
        api.request('/api/locations'),
        api.request(attendancePath),
      ]);
      users = List<dynamic>.from(result[0]);
      locations = List<dynamic>.from(result[1]);
      attendance = List<dynamic>.from(result[2]);
    } catch (e) {
      error = cleanError(e);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> changeMonth(int delta) async {
    selectedMonth = DateTime(selectedMonth.year, selectedMonth.month + delta, 1);
    await refresh();
  }

  Future<void> pickMonth() async {
    final picked = await showDatePicker(
      context: context,
      firstDate: DateTime(2020),
      lastDate: DateTime(2035, 12, 31),
      initialDate: selectedMonth,
      helpText: 'Vyber deň v požadovanom mesiaci',
    );
    if (picked != null) {
      selectedMonth = DateTime(picked.year, picked.month, 1);
      await refresh();
    }
  }

  Future<void> openEmployee([Map<String, dynamic>? item]) async {
    final saved = await Navigator.push<bool>(
      context,
      MaterialPageRoute(
        builder: (_) => AdminEmployeePage(employee: item, locations: locations),
      ),
    );
    if (saved == true) await refresh();
  }

  Future<void> openLocation([Map<String, dynamic>? item]) async {
    final saved = await Navigator.push<bool>(
      context,
      MaterialPageRoute(builder: (_) => AdminLocationPage(location: item)),
    );
    if (saved == true) await refresh();
  }

  Future<void> openAttendance([Map<String, dynamic>? item]) async {
    if (users.isEmpty || locations.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Najprv vytvor zamestnanca a prevádzku.')),
      );
      return;
    }
    final saved = await Navigator.push<bool>(
      context,
      MaterialPageRoute(
        builder: (_) => AdminAttendancePage(
          item: item,
          users: users,
          locations: locations,
        ),
      ),
    );
    if (saved == true) await refresh();
  }

  Future<void> deleteUser(Map<String, dynamic> item) async {
    final yes = await confirmDialog(
      context,
      title: 'Odstrániť zamestnanca?',
      text:
          '${item['name']}\nAk má zamestnanec dochádzku, odstránenie nebude povolené. V takom prípade ho môžeš deaktivovať.',
    );
    if (!yes) return;
    try {
      await api.request('/api/users/${item['id']}', method: 'DELETE');
      await refresh();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> toggleUser(Map<String, dynamic> item) async {
    try {
      await api.request('/api/users/${item['id']}/active', method: 'PATCH');
      await refresh();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> deleteLocation(Map<String, dynamic> item) async {
    final yes = await confirmDialog(
      context,
      title: 'Odstrániť prevádzku?',
      text:
          '${item['name']}\nPoužitú prevádzku server z bezpečnostných dôvodov neodstráni.',
    );
    if (!yes) return;
    try {
      await api.request('/api/locations/${item['id']}', method: 'DELETE');
      await refresh();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> deleteAttendance(Map<String, dynamic> item) async {
    final yes = await confirmDialog(
      context,
      title: 'Odstrániť dochádzku?',
      text: '${displayIsoDate(item['work_date'].toString())} – ${item['user_name']}',
    );
    if (!yes) return;
    try {
      await api.request('/api/attendance/${item['id']}', method: 'DELETE');
      await refresh();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    const titles = ['Zamestnanci', 'Prevádzky', 'Dochádzka'];
    return Scaffold(
      appBar: AppBar(
        title: BrandAppTitle('Admin – ${titles[index]}'),
        actions: [
          IconButton(onPressed: refresh, icon: const Icon(Icons.refresh)),
          IconButton(onPressed: widget.onLogout, icon: const Icon(Icons.logout)),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () {
          if (index == 0) openEmployee();
          if (index == 1) openLocation();
          if (index == 2) openAttendance();
        },
        icon: const Icon(Icons.add),
        label: Text(index == 0
            ? 'Zamestnanec'
            : index == 1
                ? 'Prevádzka'
                : 'Záznam'),
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: index,
        onDestinationSelected: (value) => setState(() => index = value),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.people_outline), label: 'Zamestnanci'),
          NavigationDestination(icon: Icon(Icons.factory_outlined), label: 'Prevádzky'),
          NavigationDestination(icon: Icon(Icons.schedule_outlined), label: 'Dochádzka'),
        ],
      ),
      body: loading
          ? const Center(child: CircularProgressIndicator())
          : error != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(error!),
                        const SizedBox(height: 12),
                        FilledButton(onPressed: refresh, child: const Text('Skúsiť znova')),
                      ],
                    ),
                  ),
                )
              : IndexedStack(
                  index: index,
                  children: [
                    _adminEmployees(),
                    _adminLocations(),
                    _adminAttendance(),
                  ],
                ),
    );
  }

  Widget _adminEmployees() {
    if (users.isEmpty) {
      return const Center(child: Text('Zatiaľ nie sú vytvorení zamestnanci.'));
    }
    return RefreshIndicator(
      onRefresh: refresh,
      child: ListView.builder(
        padding: const EdgeInsets.fromLTRB(12, 12, 12, 90),
        itemCount: users.length,
        itemBuilder: (context, i) {
          final item = Map<String, dynamic>.from(users[i]);
          final active = item['active'] == true;
          return Card(
            child: ListTile(
              onTap: () => openEmployee(item),
              leading: CircleAvatar(child: Text((item['name']?.toString() ?? '?').substring(0, 1))),
              title: Text(item['name']?.toString() ?? ''),
              subtitle: Text(
                '${item['personal_number']} • ${item['login']}\n${item['location_name'] ?? ''} • ${active ? 'Aktívny' : 'Neaktívny'}',
              ),
              isThreeLine: true,
              trailing: PopupMenuButton<String>(
                onSelected: (value) {
                  if (value == 'edit') openEmployee(item);
                  if (value == 'toggle') toggleUser(item);
                  if (value == 'delete') deleteUser(item);
                },
                itemBuilder: (_) => [
                  const PopupMenuItem(value: 'edit', child: Text('Upraviť / heslo')),
                  PopupMenuItem(
                    value: 'toggle',
                    child: Text(active ? 'Deaktivovať' : 'Aktivovať'),
                  ),
                  const PopupMenuItem(value: 'delete', child: Text('Odstrániť')),
                ],
              ),
            ),
          );
        },
      ),
    );
  }

  Widget _adminLocations() {
    if (locations.isEmpty) {
      return const Center(child: Text('Zatiaľ nie sú vytvorené prevádzky.'));
    }
    return RefreshIndicator(
      onRefresh: refresh,
      child: ListView.builder(
        padding: const EdgeInsets.fromLTRB(12, 12, 12, 90),
        itemCount: locations.length,
        itemBuilder: (context, i) {
          final item = Map<String, dynamic>.from(locations[i]);
          return Card(
            child: ListTile(
              onTap: () => openLocation(item),
              leading: const CircleAvatar(child: Icon(Icons.factory_outlined)),
              title: Text(item['name']?.toString() ?? ''),
              subtitle: Text(
                [item['city'], item['address']]
                    .where((value) => (value ?? '').toString().isNotEmpty)
                    .join(' • '),
              ),
              trailing: PopupMenuButton<String>(
                onSelected: (value) {
                  if (value == 'edit') openLocation(item);
                  if (value == 'delete') deleteLocation(item);
                },
                itemBuilder: (_) => const [
                  PopupMenuItem(value: 'edit', child: Text('Upraviť')),
                  PopupMenuItem(value: 'delete', child: Text('Odstrániť')),
                ],
              ),
            ),
          );
        },
      ),
    );
  }

  Widget _adminAttendance() {
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 12, 12, 4),
          child: MonthSelector(
            month: selectedMonth,
            onPrevious: () => changeMonth(-1),
            onNext: () => changeMonth(1),
            onPick: pickMonth,
            onCurrent: () async {
              selectedMonth = monthStart(DateTime.now());
              await refresh();
            },
          ),
        ),
        Expanded(
          child: attendance.isEmpty
              ? const Center(child: Text('V tomto mesiaci nie sú záznamy.'))
              : RefreshIndicator(
                  onRefresh: refresh,
                  child: ListView.builder(
                    padding: const EdgeInsets.fromLTRB(12, 4, 12, 90),
                    itemCount: attendance.length,
                    itemBuilder: (context, i) {
                      final item = Map<String, dynamic>.from(attendance[i]);
                      return Card(
                        child: ListTile(
                          onTap: () => openAttendance(item),
                          title: Text(
                            '${displayIsoDate(item['work_date'].toString())} • ${item['user_name']}',
                          ),
                          subtitle: Text(
                            '${item['location_name']} • ${item['type']}\n'
                            '${item['time_from'] ?? '—'}${item['time_to'] == null ? '' : ' – ${item['time_to']}'} • ${((item['hours'] as num?) ?? 0).toStringAsFixed(2)} h • ${item['status']}',
                          ),
                          isThreeLine: true,
                          trailing: PopupMenuButton<String>(
                            onSelected: (value) {
                              if (value == 'edit') openAttendance(item);
                              if (value == 'delete') deleteAttendance(item);
                            },
                            itemBuilder: (_) => const [
                              PopupMenuItem(value: 'edit', child: Text('Upraviť')),
                              PopupMenuItem(value: 'delete', child: Text('Odstrániť')),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
                ),
        ),
      ],
    );
  }
}

class AdminEmployeePage extends StatefulWidget {
  final Map<String, dynamic>? employee;
  final List<dynamic> locations;
  const AdminEmployeePage({
    super.key,
    required this.employee,
    required this.locations,
  });

  @override
  State<AdminEmployeePage> createState() => _AdminEmployeePageState();
}

class _AdminEmployeePageState extends State<AdminEmployeePage> {
  late final TextEditingController personalNumber;
  late final TextEditingController name;
  late final TextEditingController login;
  final password = TextEditingController();
  int? locationId;
  bool active = true;
  bool busy = false;
  String? error;

  bool get editing => widget.employee != null;

  @override
  void initState() {
    super.initState();
    final item = widget.employee;
    personalNumber = TextEditingController(text: item?['personal_number']?.toString() ?? '');
    name = TextEditingController(text: item?['name']?.toString() ?? '');
    login = TextEditingController(text: item?['login']?.toString() ?? '');
    locationId = item?['location_id'] as int?;
    active = item?['active'] as bool? ?? true;
    if (locationId == null && widget.locations.isNotEmpty) {
      locationId = widget.locations.first['id'] as int;
    }
  }

  @override
  void dispose() {
    personalNumber.dispose();
    name.dispose();
    login.dispose();
    password.dispose();
    super.dispose();
  }

  Future<void> save() async {
    if (locationId == null) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final body = <String, dynamic>{
        'personal_number': personalNumber.text.trim(),
        'name': name.text.trim(),
        'login': login.text.trim(),
        'location_id': locationId,
        'active': active,
      };
      if (!editing || password.text.isNotEmpty) body['password'] = password.text;
      await api.request(
        editing ? '/api/users/${widget.employee!['id']}' : '/api/users',
        method: editing ? 'PATCH' : 'POST',
        body: body,
      );
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) setState(() => error = cleanError(e));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: BrandAppTitle(editing ? 'Upraviť zamestnanca' : 'Nový zamestnanec'),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(controller: personalNumber, decoration: const InputDecoration(labelText: 'Osobné číslo')),
          const SizedBox(height: 12),
          TextField(controller: name, decoration: const InputDecoration(labelText: 'Meno')),
          const SizedBox(height: 12),
          TextField(controller: login, decoration: const InputDecoration(labelText: 'Login')),
          const SizedBox(height: 12),
          TextField(
            controller: password,
            obscureText: true,
            decoration: InputDecoration(
              labelText: editing ? 'Nové heslo (nepovinné)' : 'Heslo',
              helperText: editing ? 'Prázdne pole = heslo sa nemení' : null,
            ),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<int>(
            initialValue: locationId,
            decoration: const InputDecoration(labelText: 'Prevádzka'),
            items: widget.locations
                .map<DropdownMenuItem<int>>(
                  (item) => DropdownMenuItem<int>(
                    value: item['id'] as int,
                    child: Text(item['name'].toString()),
                  ),
                )
                .toList(),
            onChanged: (value) => setState(() => locationId = value),
          ),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Aktívny účet'),
            value: active,
            onChanged: (value) => setState(() => active = value),
          ),
          if (error != null)
            Text(error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: busy ? null : save,
            child: busy
                ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2))
                : const Text('Uložiť'),
          ),
        ],
      ),
    );
  }
}

class AdminLocationPage extends StatefulWidget {
  final Map<String, dynamic>? location;
  const AdminLocationPage({super.key, this.location});

  @override
  State<AdminLocationPage> createState() => _AdminLocationPageState();
}

class _AdminLocationPageState extends State<AdminLocationPage> {
  late final TextEditingController name;
  late final TextEditingController city;
  late final TextEditingController address;
  bool busy = false;
  String? error;

  bool get editing => widget.location != null;

  @override
  void initState() {
    super.initState();
    name = TextEditingController(text: widget.location?['name']?.toString() ?? '');
    city = TextEditingController(text: widget.location?['city']?.toString() ?? '');
    address = TextEditingController(text: widget.location?['address']?.toString() ?? '');
  }

  @override
  void dispose() {
    name.dispose();
    city.dispose();
    address.dispose();
    super.dispose();
  }

  Future<void> save() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await api.request(
        editing ? '/api/locations/${widget.location!['id']}' : '/api/locations',
        method: editing ? 'PATCH' : 'POST',
        body: {
          'name': name.text.trim(),
          'city': city.text.trim(),
          'address': address.text.trim(),
        },
      );
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) setState(() => error = cleanError(e));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: BrandAppTitle(editing ? 'Upraviť prevádzku' : 'Nová prevádzka'),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(controller: name, decoration: const InputDecoration(labelText: 'Názov')),
          const SizedBox(height: 12),
          TextField(controller: city, decoration: const InputDecoration(labelText: 'Mesto')),
          const SizedBox(height: 12),
          TextField(controller: address, decoration: const InputDecoration(labelText: 'Adresa')),
          if (error != null) ...[
            const SizedBox(height: 12),
            Text(error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
          const SizedBox(height: 18),
          FilledButton(
            onPressed: busy ? null : save,
            child: busy
                ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2))
                : const Text('Uložiť'),
          ),
        ],
      ),
    );
  }
}

class AdminAttendancePage extends StatefulWidget {
  final Map<String, dynamic>? item;
  final List<dynamic> users;
  final List<dynamic> locations;
  const AdminAttendancePage({
    super.key,
    this.item,
    required this.users,
    required this.locations,
  });

  @override
  State<AdminAttendancePage> createState() => _AdminAttendancePageState();
}

class _AdminAttendancePageState extends State<AdminAttendancePage> {
  DateTime day = DateTime.now();
  int? userId;
  int? locationId;
  String type = 'Práca';
  String status = 'approved';
  TimeOfDay from = const TimeOfDay(hour: 8, minute: 0);
  TimeOfDay to = const TimeOfDay(hour: 16, minute: 0);
  late final TextEditingController breakCtrl;
  late final TextEditingController noteCtrl;
  bool busy = false;
  String? error;

  static const types = [
    'Práca',
    'Dovolenka',
    'Lekár',
    'PN',
    'OČR',
    'Náhradné voľno',
    'Iné',
  ];

  bool get editing => widget.item != null;

  @override
  void initState() {
    super.initState();
    final item = widget.item;
    day = DateTime.tryParse(item?['work_date']?.toString() ?? '') ?? DateTime.now();
    userId = item?['user_id'] as int? ?? (widget.users.isNotEmpty ? widget.users.first['id'] as int : null);
    locationId = item?['location_id'] as int? ??
        (widget.locations.isNotEmpty ? widget.locations.first['id'] as int : null);
    type = item?['type']?.toString() ?? 'Práca';
    status = item?['status']?.toString() ?? 'approved';
    from = parseTime(item?['time_from']?.toString(), const TimeOfDay(hour: 8, minute: 0));
    to = parseTime(item?['time_to']?.toString(), const TimeOfDay(hour: 16, minute: 0));
    breakCtrl = TextEditingController(text: '${item?['break_minutes'] ?? 30}');
    noteCtrl = TextEditingController(text: item?['note']?.toString() ?? '');
  }

  @override
  void dispose() {
    breakCtrl.dispose();
    noteCtrl.dispose();
    super.dispose();
  }

  Future<void> save() async {
    if (userId == null || locationId == null) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final body = <String, dynamic>{
        'work_date': isoDate(day),
        'user_id': userId,
        'location_id': locationId,
        'type': type,
        'time_from': (type == 'Práca' || type == 'Lekár') ? formatTime(from) : null,
        'time_to': (type == 'Práca' || type == 'Lekár') ? formatTime(to) : null,
        'break_minutes': type == 'Práca' ? int.tryParse(breakCtrl.text) ?? 0 : 0,
        'note': noteCtrl.text.trim(),
      };

      if (editing) {
        body['status'] = status;
        await api.request(
          '/api/attendance/${widget.item!['id']}',
          method: 'PATCH',
          body: body,
        );
      } else {
        final created = Map<String, dynamic>.from(
          await api.request('/api/attendance', method: 'POST', body: body),
        );
        if (status != 'approved') {
          await api.request(
            '/api/attendance/${created['id']}',
            method: 'PATCH',
            body: {'status': status},
          );
        }
      }
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) setState(() => error = cleanError(e));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final usesTime = type == 'Práca' || type == 'Lekár';
    return Scaffold(
      appBar: AppBar(
        title: BrandAppTitle(editing ? 'Upraviť dochádzku' : 'Nová dochádzka'),
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Dátum'),
            subtitle: Text(displayDate(day)),
            trailing: const Icon(Icons.calendar_month),
            onTap: () async {
              final picked = await showDatePicker(
                context: context,
                firstDate: DateTime(2020),
                lastDate: DateTime(2035, 12, 31),
                initialDate: day,
              );
              if (picked != null) setState(() => day = picked);
            },
          ),
          DropdownButtonFormField<int>(
            initialValue: userId,
            decoration: const InputDecoration(labelText: 'Zamestnanec'),
            items: widget.users
                .map<DropdownMenuItem<int>>(
                  (item) => DropdownMenuItem<int>(
                    value: item['id'] as int,
                    child: Text('${item['personal_number']} – ${item['name']}'),
                  ),
                )
                .toList(),
            onChanged: (value) => setState(() => userId = value),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<int>(
            initialValue: locationId,
            decoration: const InputDecoration(labelText: 'Prevádzka'),
            items: widget.locations
                .map<DropdownMenuItem<int>>(
                  (item) => DropdownMenuItem<int>(
                    value: item['id'] as int,
                    child: Text(item['name'].toString()),
                  ),
                )
                .toList(),
            onChanged: (value) => setState(() => locationId = value),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: type,
            decoration: const InputDecoration(labelText: 'Typ'),
            items: types
                .map((value) => DropdownMenuItem(value: value, child: Text(value)))
                .toList(),
            onChanged: (value) => setState(() => type = value!),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: status,
            decoration: const InputDecoration(labelText: 'Stav'),
            items: const [
              DropdownMenuItem(value: 'approved', child: Text('Schválené')),
              DropdownMenuItem(value: 'pending', child: Text('Čaká na schválenie')),
              DropdownMenuItem(value: 'rejected', child: Text('Zamietnuté')),
            ],
            onChanged: (value) => setState(() => status = value!),
          ),
          if (usesTime) ...[
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () async {
                      final picked = await showTimePicker(context: context, initialTime: from);
                      if (picked != null) setState(() => from = picked);
                    },
                    child: Text('Od ${formatTime(from)}'),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: OutlinedButton(
                    onPressed: () async {
                      final picked = await showTimePicker(context: context, initialTime: to);
                      if (picked != null) setState(() => to = picked);
                    },
                    child: Text('Do ${formatTime(to)}'),
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
              decoration: const InputDecoration(labelText: 'Prestávka v minútach'),
            ),
          ],
          const SizedBox(height: 12),
          TextField(
            controller: noteCtrl,
            maxLines: 3,
            decoration: const InputDecoration(labelText: 'Poznámka'),
          ),
          if (error != null) ...[
            const SizedBox(height: 12),
            Text(error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
          const SizedBox(height: 18),
          FilledButton(
            onPressed: busy ? null : save,
            child: busy
                ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2))
                : const Text('Uložiť'),
          ),
        ],
      ),
    );
  }
}
