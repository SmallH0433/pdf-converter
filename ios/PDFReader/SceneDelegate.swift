import UIKit

final class SceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?
    private var pendingURL: URL?

    func scene(
        _ scene: UIScene,
        willConnectTo session: UISceneSession,
        options connectionOptions: UIScene.ConnectionOptions
    ) {
        guard let windowScene = scene as? UIWindowScene else { return }
        let window = UIWindow(windowScene: windowScene)
        let home = HomeViewController()
        let navigation = UINavigationController(rootViewController: home)
        navigation.setNavigationBarHidden(true, animated: false)
        window.rootViewController = navigation
        window.makeKeyAndVisible()
        self.window = window

        if let url = connectionOptions.urlContexts.first?.url {
            pendingURL = url
            DispatchQueue.main.async { [weak self, weak home] in
                guard let url = self?.pendingURL else { return }
                self?.pendingURL = nil
                home?.openDocument(at: url)
            }
        }
    }

    func scene(_ scene: UIScene, openURLContexts URLContexts: Set<UIOpenURLContext>) {
        guard let url = URLContexts.first?.url else { return }
        if let home = (window?.rootViewController as? UINavigationController)?.viewControllers.first
            as? HomeViewController {
            home.openDocument(at: url)
        } else {
            NotificationCenter.default.post(name: .openPDFURL, object: url)
        }
    }
}
