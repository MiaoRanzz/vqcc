import { useEffect, useState } from "react";
import {
  Activity,
  ArrowRight,
  BookOpen,
  Boxes,
  GraduationCap,
  ChevronRight,
  FlaskConical,
  LayoutDashboard,
  LogOut,
  Menu,
  Plus,
  Send,
  Settings2,
  ShieldCheck,
} from "lucide-react";
import { mutate, request, setCsrf } from "./api/client";
import { Notice } from "./components/ui";
import Overview from "./pages/Overview";
import Jobs from "./pages/Jobs";
import Experiments from "./pages/Experiments";
import Workbench from "./pages/Workbench";
import Research from "./pages/Research";
import Submissions from "./pages/Submissions";
import Config from "./pages/Config";
import Tasks from "./pages/Tasks";
const navigation = [
  ["/", "实验总览", LayoutDashboard],
  ["/tasks", "任务介绍", GraduationCap],
  ["/jobs", "任务与队列", Activity],
  ["/experiments", "实验与证据", FlaskConical],
  ["/workbench", "启动工作台", Plus],
  ["/research", "研究假设", BookOpen],
  ["/submissions", "提交中心", Send],
  ["/config", "配置与额度", Settings2],
] as const;
export default function App() {
  const [session, setSession] = useState<{
      csrf_token: string;
      read_only: boolean;
    } | null>(null),
    [checking, setChecking] = useState(true),
    [hash, setHash] = useState(location.hash.slice(1) || "/"),
    [connection, setConnection] = useState("连接中"),
    [mobile, setMobile] = useState(false);
  useEffect(() => {
    request<{ csrf_token: string; read_only: boolean }>("/session")
      .then((value) => {
        setCsrf(value.csrf_token);
        setSession(value);
      })
      .catch(() => {})
      .finally(() => setChecking(false));
    const expired = () => setSession(null);
    window.addEventListener("session-expired", expired);
    return () => window.removeEventListener("session-expired", expired);
  }, []);
  useEffect(() => {
    const change = () => {
      setHash(location.hash.slice(1) || "/");
      setMobile(false);
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);
  useEffect(() => {
    if (!session) return;
    let lastId = "";
    let timer: number | undefined;
    const events = new EventSource("/api/v1/events");
    const update = (event: MessageEvent) => {
      if (event.lastEventId && event.lastEventId === lastId) return;
      lastId = event.lastEventId;
      if (!timer)
        timer = window.setTimeout(() => {
          window.dispatchEvent(new Event("console-update"));
          timer = undefined;
        }, 200);
    };
    events.onopen = () => setConnection("实时连接");
    events.onerror = () => setConnection("连接恢复中 · 状态定时更新");
    events.onmessage = update;
    events.addEventListener("resync", () =>
      window.dispatchEvent(new Event("console-update")),
    );
    return () => {
      events.close();
      clearTimeout(timer);
    };
  }, [session]);
  const [pathname, query = ""] = hash.split("?"),
    params = new URLSearchParams(query),
    current = navigation.find(([path]) => path === pathname) || navigation[0];
  if (checking)
    return (
      <div className="startup">
        VQCC <span>正在连接私有控制台…</span>
      </div>
    );
  if (!session)
    return (
      <Login
        onLogin={(value) => {
          setCsrf(value.csrf_token);
          setSession(value);
        }}
      />
    );
  let page;
  switch (pathname) {
    case "/tasks":
      page = <Tasks params={params} />;
      break;
    case "/jobs":
      page = <Jobs params={params} />;
      break;
    case "/experiments":
      page = <Experiments params={params} />;
      break;
    case "/workbench":
      page = <Workbench key={hash} params={params} />;
      break;
    case "/research":
      page = <Research />;
      break;
    case "/submissions":
      page = <Submissions />;
      break;
    case "/config":
      page = <Config />;
      break;
    default:
      page = <Overview />;
  }
  return (
    <div className="shell">
      <aside className={`sidebar ${mobile ? "open" : ""}`}>
        <a href="#/" className="brand">
          <div className="brand-mark">
            <Boxes size={25} />
          </div>
          <span>
            VQCC<small>RESEARCH CONSOLE</small>
          </span>
        </a>
        <div className="workspace-label">
          私人工作空间 <span>LOCAL</span>
        </div>
        <nav aria-label="主导航">
          {navigation.map(([path, title, Icon]) => (
            <a
              key={path}
              href={`#${path}`}
              className={path === pathname ? "active" : ""}
              aria-current={path === pathname ? "page" : undefined}
            >
              <Icon size={18} />
              {title}
              {path === pathname && (
                <ChevronRight className="nav-chevron" size={15} />
              )}
            </a>
          ))}
        </nav>
        <div className="sidebar-footer">
          <ShieldCheck size={18} />
          <div>
            私有访问<small>通过 SSH 转发连接</small>
          </div>
        </div>
        <button
          className="logout"
          onClick={() =>
            mutate("/session", {}, "DELETE").then(() => setSession(null))
          }
        >
          <LogOut size={15} /> 退出会话
        </button>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <button
            className="mobile-toggle"
            aria-label="打开导航"
            onClick={() => setMobile(!mobile)}
          >
            <Menu size={20} />
          </button>
          <div className="breadcrumb">
            控制台 <ChevronRight size={13} />
            <strong>{current[1]}</strong>
          </div>
          <div className="topbar-right">
            <span
              className={`connection ${connection === "实时连接" ? "online" : ""}`}
            >
              <i />
              {connection}
            </span>
            <span className="timezone">北京时间 UTC+8</span>
            <span className="avatar">V</span>
          </div>
        </header>
        <main key={pathname}>
          {session.read_only && (
            <div className="notice info">
              只读验收模式 · 可以浏览状态和预检，执行与配置写入尚未启用。
            </div>
          )}
          {page}
          <footer className="page-footer">
            <span>VQCC · 可验证量子电路编译</span>
            <span>本地测量不代表平台评分</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
function Login({
  onLogin,
}: {
  onLogin: (session: { csrf_token: string; read_only: boolean }) => void;
}) {
  const [key, setKey] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  return (
    <div className="login-shell">
      <div className="login-story">
        <div className="brand">
          <div className="brand-mark">
            <Boxes size={27} />
          </div>
          <span>
            VQCC<small>RESEARCH CONSOLE</small>
          </span>
        </div>
        <div>
          <p className="eyebrow light">VERIFY. IMPROVE. REPEAT.</p>
          <h1>
            让每一次改进，
            <br />
            都有依据。
          </h1>
          <p>
            研究、实验、完整验证与提交，
            <br />
            在同一个私有工作空间中连接。
          </p>
        </div>
        <span className="login-bottom">DQI / INVSQRT / DFTHC-SOS</span>
      </div>
      <div className="login-form">
        <div className="login-form-inner">
          <ShieldCheck size={30} className="text-green" />
          <p className="eyebrow">PRIVATE WORKSPACE</p>
          <h2>连接实验控制台</h2>
          <p className="muted">
            经 SSH 读取服务器上的会话引导密钥，建立本机私有会话。
          </p>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              setError("");
              try {
                onLogin(
                  await request("/session", {
                    method: "POST",
                    body: JSON.stringify({ key }),
                  }),
                );
                setKey("");
              } catch (err) {
                setError((err as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <label className="field">
              <span>会话引导密钥</span>
              <input
                type="password"
                required
                autoComplete="off"
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder="输入服务器私有密钥"
              />
            </label>
            <Notice error={error} />
            <button className="primary" disabled={busy}>
              {busy ? "正在连接…" : "进入工作空间"}
              <ArrowRight size={17} />
            </button>
          </form>
          <p className="login-hint">
            默认仅监听 127.0.0.1。密钥不会写入浏览器地址或业务日志。
          </p>
        </div>
      </div>
    </div>
  );
}
