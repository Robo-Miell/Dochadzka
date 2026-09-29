import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:dochadzka_mobile/presence_panel.dart';

void main(){
 testWidgets('operator checks in and out using server session key',(tester)async{
  var present=false;
  final calls=<String>[];
  Future<dynamic> request(String path,String method,Map<String,dynamic>? body)async{
   calls.add(path);
   if(path=='/api/locations')return [{'id':3,'name':'Test prevádzka'}];
   if(path.endsWith('check-in')){expect(body!['location_id'],3);present=true;}
   if(path.endsWith('check-out')){expect(body!['presence_key'],'test-key');present=false;}
   return {'present':present,'presence_key':'test-key','location_name':'Test prevádzka','started_at':'2026-09-29T06:00:00Z','email_configured':true};
  }
  await tester.pumpWidget(MaterialApp(home:Scaffold(body:PresencePanel(request:request))));
  await tester.pumpAndSettle();
  await tester.tap(find.text('Príchod do práce'));await tester.pumpAndSettle();
  expect(find.text('Odchod z práce'),findsOneWidget);
  await tester.tap(find.text('Odchod z práce'));await tester.pumpAndSettle();
  expect(find.text('Príchod do práce'),findsOneWidget);
  expect(calls.where((p)=>p.endsWith('check-in')).length,1);
  await tester.pumpWidget(const SizedBox());
 });
 testWidgets('admin sees occupied and empty locations',(tester)async{
  await tester.pumpWidget(MaterialApp(home:Scaffold(body:PresencePanel(admin:true,request:(path,method,body)async=>{'locations':[{'id':1,'name':'Site A','people':[{'name':'Test OP','started_at':'2026-09-29T06:00:00Z','overdue':true}]},{'id':2,'name':'Site B','people':[]}]}))));
  await tester.pumpAndSettle();
  expect(find.text('Site A · 1'),findsOneWidget);expect(find.text('Site B · 0'),findsOneWidget);
  expect(find.textContaining('Viac než 12 hodín'),findsOneWidget);
  await tester.pumpWidget(const SizedBox());
 });
}
