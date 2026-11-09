using System;
using System.Threading;
namespace CompanyNetwork {
 internal sealed class ConnectionSnapshot {
  internal bool Outer, Inner, Route, SessionsReady;
  internal string Kind { get { return Outer && Inner && Route && SessionsReady ? "connected" : !Outer && !Inner ? "disconnected" : "recovering"; } }
  internal string Message { get { return Kind == "connected" ? "公司网络已连接（会话和公司路由已就绪）。" : Kind == "disconnected" ? "公司网络已断开。" : "连接正在恢复或尚未就绪，请检查登录或重新连接。"; } }
 }
 // All interactive and command entry points share this per-user operation boundary.
 internal sealed class OperationController : IDisposable {
  readonly Mutex gate;
  readonly EventWaitHandle stop;
  readonly Func<string, Action<string>, Action, string> operate;
  readonly Func<ConnectionSnapshot> read;
  internal event Action<string> Transition;
  internal OperationController(string identity, Func<string, Action<string>, Action, string> operation, Func<ConnectionSnapshot> snapshot) {
   gate = new Mutex(false, @"Local\CompanyNetwork.Operation." + identity);
   stop = new EventWaitHandle(false, EventResetMode.ManualReset, @"Local\CompanyNetwork.Stop." + identity);
   operate = operation; read = snapshot;
  }
  internal OperationController(UserInstall user) : this(user.Sid, delegate(string action, Action<string> progress, Action check) {
   user.ReloadState(); user.CheckCancelled = check;
   user.ReportPhase = delegate(string phase) { Diagnostics.Record("phase", phase); };
   try {
    if(action == "--connect") return user.Prepare(true, true, progress);
    if(action == "--prepare-only") return user.Prepare(false, false, progress);
    if(action == "--disconnect") return user.Disconnect();
    if(action == "--remove") return user.Remove();
    if(action == "--gpt") return user.OpenGpt();
    throw new AppProblem("invalid_action", "无法识别此操作。");
   } finally { user.CheckCancelled = delegate {}; user.ReportPhase = delegate {}; }
  }, user.Snapshot) {}
  internal ConnectionSnapshot Read() {
   var elapsed = System.Diagnostics.Stopwatch.StartNew();
   try {
    ConnectionSnapshot state = read();
    Diagnostics.Record("snapshot", new { state = state.Kind, outer = state.Outer, inner = state.Inner, route = state.Route, sessionsReady = state.SessionsReady, readElapsedMs = elapsed.ElapsedMilliseconds });
    return state;
   } catch(Exception error) { Diagnostics.Failure("read", error); throw; }
  }
  internal void RequestStop() { stop.Set(); }
  internal string Execute(string action, Action<string> progress) {
   bool stopping = action == "--disconnect" || action == "--remove";
   if(stopping) { stop.Set(); progress("正在取消连接并等待断开；若超过 10 秒仍未完成，请保留窗口并稍候或重试。"); }
   bool owned = false;
   try {
    try { owned = gate.WaitOne(stopping ? 300000 : 0); } catch(AbandonedMutexException) { owned = true; }
    if(!owned) throw new AppProblem("operation_busy", "另一项操作尚未完成，请稍候；断开请求已优先通知正在连接的操作。");
    Action check = delegate { if(stop.WaitOne(0)) throw new AppProblem("connection_cancelled", "连接已取消。"); };
    if(!stopping && action != "--gpt") check();
    Emit(stopping ? "disconnecting" : action == "--connect" ? "connecting" : "working");
    Diagnostics.Record("phase", stopping ? "disconnect" : action == "--connect" ? "connect" : action == "--prepare-only" ? "prepare" : action == "--gpt" ? "gpt" : "remove");
    string result = operate(action, progress, stopping ? (Action)delegate {} : check);
    if(action == "--connect") check();
    if(stopping && Read().Kind != "disconnected") throw new AppProblem("disconnect_unconfirmed", "尚未确认两层会话均已结束，请重试断开。");
    if(stopping) stop.Reset();
    Emit(Read().Kind); return result;
   } catch(Exception failure) {
    Diagnostics.Failure(action, failure);
    if(owned && action == "--connect") {
     try { operate("--disconnect", progress, delegate {}); if(Read().Kind != "disconnected") throw new AppProblem("cleanup_failed", "未能确认取消后的两层会话已结束，请重试断开。"); }
     catch(Exception e) { Emit("failed"); throw new AppProblem("cleanup_failed", "连接未完成，且断开尚未确认：" + Program.Explain(e).Message); }
    }
    Emit("failed"); throw;
   }
   finally { if(owned) gate.ReleaseMutex(); }
  }
  void Emit(string state) { Diagnostics.Record("transition", state); Action<string> listener = Transition; if(listener != null) listener(state); }
  public void Dispose() { gate.Dispose(); stop.Dispose(); }
 }
}
