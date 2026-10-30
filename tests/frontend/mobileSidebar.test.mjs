import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';

const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url));
const ts=require('typescript');
const source=readFileSync(new URL('../../web/frontend/src/components/ResponsiveSidebar.tsx',import.meta.url),'utf8');
const {outputText}=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}});

/** Exercise real component state and callbacks; browser checks cover DOM focus/CSS. */
function setup(narrow=true){
 const state=[],refs=[];let cursor=0,refCursor=0;
 const jsx=(type,props)=>({type,props});
 const Sidebar=function NativeSidebar(){};
 class Element{constructor(navigation=false){this.navigation=navigation}closest(){return this.navigation?this:null}}
 const exports={};
 runInNewContext(outputText,{exports,window:{matchMedia:()=>({matches:narrow})},Element,
  require:specifier=>{
   if(specifier==='./Sidebar')return {__esModule:true,default:Sidebar};
   if(specifier==='react/jsx-runtime')return {jsx,jsxs:jsx,Fragment:'fragment'};
   if(specifier==='react')return {
    useState(initial){const slot=cursor++;if(!(slot in state))state[slot]=typeof initial==='function'?initial():initial;return [state[slot],value=>{state[slot]=typeof value==='function'?value(state[slot]):value}]},
    useRef(initial){const slot=refCursor++;return refs[slot]??=( {current:initial} )},
    useId:()=>':mobile-nav:',useEffect:()=>{},useLayoutEffect:()=>{},
   };
   throw Error('Unexpected dependency: '+specifier);
  },
 });
 const calls=[];
 const props={currentPage:'dashboard',activeSessionId:'same-session',selectedPersona:'same-persona',sessions:[],personas:[],gatewayStatus:'connected',apiDirect:false,agentRuntime:'codex'};
 for(const name of ['onPageChange','onSessionSelect','onPersonaChange','onNewProfile','onNewChat','onOpenSettings','onSessionDelete','onSessionRename','onSessionArchive'])props[name]=(...args)=>calls.push([name,...args]);
 function render(){cursor=0;refCursor=0;return exports.default(props)}
 const children=tree=>tree.props.children;
 const panel=tree=>children(tree).find(node=>node.props?.className?.startsWith('sidebar-panel'));
 const trigger=tree=>children(tree).find(node=>node.props?.className==='mobile-nav-bar').props.children[0];
 const native=tree=>panel(tree).props.children.find(node=>node.type===Sidebar);
 const open=()=>{trigger(render()).props.onClick();return render()};
 return {render,panel,trigger,native,open,props,calls,Element};
}

test('narrow screens start with the native sidebar inert and can open it as a modal',()=>{
 const view=setup(),initial=view.render();
 assert.equal(view.panel(initial).props.inert,true);
 assert.equal(view.panel(initial).props['aria-hidden'],true);
 assert.equal(view.trigger(initial).props['aria-expanded'],false);
 const opened=view.open();
 assert.equal(view.panel(opened).props.inert,false);
 assert.equal(view.panel(opened).props['aria-modal'],true);
 assert.equal(view.trigger(opened).props['aria-expanded'],true);
 assert.equal(view.trigger(opened).props['aria-controls'],view.panel(opened).props.id);
});

test('same-page and same-session actions dismiss the drawer without relying on a parent change',()=>{
 for(const [name,args] of [['onPageChange',['dashboard']],['onSessionSelect',['same-session']],['onPersonaChange',['same-persona']],['onNewProfile',[]],['onNewChat',[]],['onOpenSettings',[]]]){
  const view=setup(),opened=view.open();
  view.native(opened).props[name](...args);
  assert.equal(view.panel(view.render()).props.inert,true,name);
  assert.deepEqual(view.calls,[[name,...args]],name);
 }
});

test('backdrop and close controls dismiss the same mounted sidebar',()=>{
 const view=setup(),opened=view.open(),sidebarType=view.native(opened).type;
 opened.props.children.find(node=>node.props?.className?.startsWith('sidebar-backdrop')).props.onClick();
 assert.equal(view.trigger(view.render()).props['aria-expanded'],false);
 const reopened=view.open();
 const header=view.panel(reopened).props.children[0];
 header.props.children.find(node=>node.props?.['aria-label']==='关闭导航').props.onClick();
 const closed=view.render();
 assert.equal(view.panel(closed).props.inert,true);
 assert.equal(view.native(closed).type,sidebarType);
});

test('native navigation click capture also dismisses a host-owned custom nav callback',()=>{
 const view=setup(),opened=view.open();
 view.panel(opened).props.onClickCapture({target:new view.Element(true)});
 assert.equal(view.trigger(view.render()).props['aria-expanded'],false);
 assert.deepEqual(view.calls,[],'the wrapper does not invent a second navigation callback');
 const again=view.open();
 view.panel(again).props.onClickCapture({target:new view.Element(false)});
 assert.equal(view.trigger(view.render()).props['aria-expanded'],true,'other controls retain the drawer');
});

test('desktop sidebar is neither hidden nor modal and unrelated actions are forwarded intact',()=>{
 const view=setup(false),tree=view.render(),native=view.native(tree);
 assert.equal(view.panel(tree).props.inert,false);
 assert.equal(view.panel(tree).props.role,undefined);
 assert.equal(view.panel(tree).props['aria-hidden'],undefined);
 assert.equal(view.panel(tree).props['aria-modal'],undefined);
 for(const name of ['onSessionDelete','onSessionRename','onSessionArchive'])assert.equal(native.props[name],view.props[name]);
 assert.equal(native.props.sessions,view.props.sessions);
 assert.equal(native.props.personas,view.props.personas);
});
