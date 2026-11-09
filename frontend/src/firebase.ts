// Firebase の設定。これらの値は画面に埋め込んで公開される前提のもの（秘密情報ではない）。
// アクセスの制御は、サーバー側でのトークン検証と Firebase 側の設定で行う。
import { initializeApp } from "firebase/app";
import {
  GoogleAuthProvider,
  createUserWithEmailAndPassword,
  getAuth,
  onAuthStateChanged,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut,
  updateProfile,
  type User,
} from "firebase/auth";

const app = initializeApp({
  apiKey: "AIzaSyCfRqUPNpXgN-fPweDlRJt15XtGAk1JCKw",
  authDomain: "project-b136cb29-e39c-4cf1-a95.firebaseapp.com",
  projectId: "project-b136cb29-e39c-4cf1-a95",
  appId: "1:684513860011:web:34c0ea4a19ced6b7e21aee",
});

export const auth = getAuth(app);

export const loginWithGoogle = () => {
  const provider = new GoogleAuthProvider();
  // 毎回アカウント選択画面を出す（出さないと、スマホなどで前のアカウントに自動でログインされる）
  provider.setCustomParameters({ prompt: "select_account" });
  return signInWithPopup(auth, provider);
};
export const loginWithEmail = (email: string, password: string) => signInWithEmailAndPassword(auth, email, password);

/** 新規登録。表示名を設定し、トークンを更新して名前がサーバーに届くようにする。 */
export async function registerWithEmail(name: string, email: string, password: string) {
  const cred = await createUserWithEmailAndPassword(auth, email, password);
  await updateProfile(cred.user, { displayName: name });
  await cred.user.getIdToken(true);
  return cred;
}

export const resetPassword = (email: string) => sendPasswordResetEmail(auth, email);
export const logout = () => signOut(auth);
export const watchAuth = (cb: (u: User | null) => void) => onAuthStateChanged(auth, cb);

/** API に付けるトークン。期限が近いと自動で更新される。 */
export async function getToken(): Promise<string | null> {
  return (await auth.currentUser?.getIdToken()) ?? null;
}
