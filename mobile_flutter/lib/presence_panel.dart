import 'dart:async';
import 'package:flutter/material.dart';

class PresencePanel extends StatefulWidget {
  final bool admin;
  final Future<dynamic> Function(String, String, Map<String,dynamic>?) request;
  const PresencePanel({super.key,required this.request,this.admin=false});
  @override
  State<PresencePanel> createState()=>_PresencePanelState();
}
class _PresencePanelState extends State<PresencePanel> {
  Map<String,dynamic>? status;
  List<dynamic> locations=[];
  int? locationId;
  bool busy=false,loading=false;
  String? error;
  Timer? timer;
  @override
  void initState(){super.initState();load();timer=Timer.periodic(const Duration(seconds:30),(_){if(WidgetsBinding.instance.lifecycleState==AppLifecycleState.resumed)load();});}
  @override
  void dispose(){timer?.cancel();super.dispose();}
  Future<void> load() async {
    if(busy||loading)return;loading=true;
    try{
      final d=await widget.request(widget.admin?'/api/presence/overview':'/api/presence/me','GET',null);
      final ls=widget.admin?d['locations']:await widget.request('/api/locations','GET',null);
      if(!mounted)return;
      setState((){status=Map<String,dynamic>.from(d);locations=List<dynamic>.from(ls);error=null;if(!locations.any((l)=>l['id']==locationId))locationId=locations.isEmpty?null:locations.first['id'] as int;});
    }catch(e){if(mounted)setState(()=>error=e.toString());}finally{loading=false;}
  }
  String since(dynamic value){final d=DateTime.tryParse(value?.toString()??'')?.toLocal();return d==null?'': '${d.day}.${d.month}.${d.year} ${d.hour.toString().padLeft(2,'0')}:${d.minute.toString().padLeft(2,'0')}';}
  Future<void> change() async {
    setState(()=>busy=true);
    try{
      final present=status?['present']==true;
      await widget.request(present?'/api/presence/check-out':'/api/presence/check-in','POST',present?{'presence_key':status!['presence_key']}:{'location_id':locationId});
      if(mounted)setState(()=>error=null);
    }catch(e){if(mounted)setState(()=>error=e.toString());return;}finally{if(mounted)setState(()=>busy=false);}
    await load();
  }
  @override
  Widget build(BuildContext context){
    final present=status?['present']==true;
    return Card(child:Padding(padding:const EdgeInsets.all(16),child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
      Text(widget.admin?'Aktuálne v práci':'Moja prítomnosť',style:Theme.of(context).textTheme.titleLarge),
      if(error!=null)Text(error!,style:TextStyle(color:Theme.of(context).colorScheme.error)),
      if(status==null)TextButton(onPressed:load,child:const Text('Načítať prítomnosť')),
      if(widget.admin)...locations.map((l)=>Padding(padding:const EdgeInsets.symmetric(vertical:8),child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[
        Text('${l['name']} · ${(l['people'] as List).length}',style:const TextStyle(fontWeight:FontWeight.bold)),
        if((l['people'] as List).isEmpty)const Text('Nikto nie je prihlásený.'),
        ...(l['people'] as List).map((p)=>Text('${p['name']} · od ${since(p['started_at'])}${p['overdue']==true?' · Viac než 12 hodín':''}')),
      ]))),
      if(!widget.admin&&status!=null)...[
        Text(present?'V práci: ${status!['location_name']} · od ${since(status!['started_at'])}':'Momentálne nie si označený ako prítomný.'),
        if(!present)DropdownButtonFormField<int>(initialValue:locationId,isExpanded:true,decoration:const InputDecoration(labelText:'Prevádzka'),items:locations.map((l)=>DropdownMenuItem<int>(value:l['id'] as int,child:Text(l['name'].toString()))).toList(),onChanged:busy?null:(v)=>setState(()=>locationId=v)),
        const SizedBox(height:8),
        FilledButton(onPressed:busy||(!present&&locationId==null)?null:change,child:Text(busy?'Ukladám…':present?'Odchod z práce':'Príchod do práce')),
        const Text('Výkaz dochádzky vyplň ako doteraz.'),
        if(status!['email_configured']!=true)const Text('Pre pripomienku po 12 hodinách požiadaj admina o doplnenie e-mailu.'),
      ],
    ])));
  }
}
