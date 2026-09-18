/// Requires the same payload in three separate camera frames.
class LabelScan {
  final Map<String, int> sightings = {};
  final Map<String, Set<String>> candidates = {};
  final Map<String, String> choices = {};

  void addFrame(Iterable<String> rawCodes) {
    final frame = <String>{};
    for (final raw in rawCodes) {
      for (final line in raw.split(RegExp(r'[\r\n\t\x1d\x1e;]+'))) {
        final text = line.trim();
        if (RegExp(r'^[PSQ].+$').hasMatch(text)) frame.add(text);
      }
    }
    for (final text in frame) {
      final count = (sightings[text] ?? 0) + 1;
      sightings[text] = count;
      if (count >= 3) {
        candidates.putIfAbsent(text[0], () => <String>{}).add(text.substring(1));
      }
    }
  }

  String? selected(String prefix) {
    final values = candidates[prefix];
    if (values == null || values.isEmpty) return null;
    return choices[prefix] ?? (values.length == 1 ? values.single : null);
  }

  bool get ready => candidates.isNotEmpty && candidates.keys.every((p) => selected(p) != null);
  List<String> get result => candidates.keys.map((p) => '$p${selected(p)!}').toList();
  void clear() { sightings.clear(); candidates.clear(); choices.clear(); }
}
