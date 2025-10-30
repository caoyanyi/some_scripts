function FindProxyForURL(url, host) {
    var socksUSA = 'SOCKS5 10.8.0.1:3127';
    var socksHKG = 'SOCKS5 10.8.0.1:3127';
    var socksKOR = 'SOCKS5 10.8.0.1:3127';

    var ipSeg = parseInt(myIpAddress().split('.')[3]);
    var socksProxy = [socksUSA, socksHKG][(ipSeg % 2)];

    // 主要域名匹配规则（按字母顺序排序）
    var domainPatterns = [
        '1e100.net', '466453.com', 'abc.xyz', 'abebooks.com', 'about.google',
        'accountkit.com', 'accounts.adobe.com', 'accounts.frame.io', 'admob.com',
        'adsense.com', 'advertisercommunity.com', 'agoogleaday.com',
        'ai.google', 'amazon.co.jp', 'amazonaws.com', 'android.com',
        'androidify.com', 'androidtv.com', 'apache.org',
        'api.ai', 'app.frame.io', 'appspot.com', 'autodraw.com',
        'behance.net', 'bing.com', 'blog.google', 'blogblog.com',
        'blogger', 'blogspot.', 'capitalg.com', 'cdn-images.mailchimp.com',
        'cdn.jsdelivr.net', 'cdninstagram.com', 'certificate-transparency.org',
        'chatgpt', 'chrome.com', 'chromecast.com', 'chromeenterprise.google',
        'chromeexperiments.com', 'chromercise.com', 'chromestatus.com',
        'chromium.org', 'cl.ly', 'cmmiinstitute.com', 'com.google',
        'comodo.net', 'connect.facebook.net', 'crates.io', 'crbug.com',
        'creativelab5.com', 'crisisresponse.google', 'crrev.com',
        'curl.se', 'data-vocabulary.org', 'debug.com', 'deepl.com', 'deepmind.com',
        'deja.com', 'design.google', 'digicert.com', 'digisfera.com',
        'discord', 'discordapp.com', 'docker.com', 'dns.google',
        'domains.google', 'duck.com', 'environment.google', 'facebook',
        'feedburner.com', 'firebaseio.com', 'fontawesome.com', 'forefront.ai',
        'f8.com', 'fb.com', 'fb.me', 'fb.watch', 'fbcdn', 'fbsbx.com',
        'fbworkmail.com', 'fotolia', 'freedb.org', 'ftcdn.net', 'g.co',
        'gcr.io', 'get.app', 'get.dev', 'get.how', 'get.page',
        'getcloudapp.com', 'getmdl.io', 'getoutline.org',
        'ggpht.com', 'github', 'gmail', 'gmodules.com', 'godaddy.com',
        'godoc.org', 'golang.org', 'google', 'gravatar.com', 'grow.google',
        'gstatic', 'gv.com', 'gvt0.com', 'gvt1.com', 'gvt3.com',
        'gwtproject.org', 'heroku.com', 'hiisw', 'html5rocks.com',
        'iam.soy', 'ietf.org', 'igoogle.com', 'instagram.com',
        'ioncube.com', 'ipinfo.io', 'itasoftware.com', 'itunes.apple.com',
        'kenengba.com', 'lers.google', 'like.com', 'linkedin.com',
        'lm.licenses.adobe.com', 'madewithcode.com', 'maps.google.com',
        'material.io', 'm.me', 'mediawiki.org', 'medium.com', 'messenger.com',
        'mozilla.org', 'mp3licensing.com', 'msdn.microsoft.com',
        'myportfolio.com', 'name.com', 'neeva.com', 'news.ycombinator.com',
        'nic.google', 'oculus.com', 'oculuscdn.com', 'omniroot.com',
        'on2.com', 'openai', 'open-assistant.io', 'opensource.google',
        'openvpn', 'oz-prod', 'pages.dev', 'panoramio.com', 'parse.com',
        'periscope.tv', 'phind.com', 'php.net', 'picasaweb.com',
        'pinterest.com', 'pki.goog', 'play.google.com', 'plus.codes',
        'poe.com', 'polymer-project.org', 'pride.google',
        'prosite.com', 'pscp.tv', 'quora', 'reddit.com', 'rocksdb.org',
        'rust-lang.org', 's3.amazonaws.com', 'savannah.gnu.org',
        'savethedate.foo', 'schema.org', 'shutterfly.com',
        'shattered.io', 'shop.lwr.one', 'singlelogin.me',
        'sipml5.org', 'soundcloud.com', 'sourceforge.net',
        'ssls.com', 'stackexchange.com', 'stackoverflow.com',
        'stories.google', 'subversion.tigris.org', 'superuser.com',
        'sustainability.google', 'symantec.com', 'synergyse.com',
        't.co', 'teachparentstech.org', 'telegram', 'tensorflow.org',
        'thefacebook.com', 'thawte.com', 'thinkwithgoogle.com',
        'tiltbrush.com', 'translate.google', 'tweetdeck.com',
        'twimg.com', 'twitpic.com', 'twitter', 'typeform.com',
        'unity.com', 'urchin.com', 'uservoice.com', 'v2ex.com',
        'vercel.ai', 'verisign.com', 'vine.co', 'waveprotocol.org',
        'waymo.com', 'web.dev', 'webmproject.org', 'webrtc.org',
        'whatbrowser.org', 'whatsapp', 'widevine.com',
        'wikibooks.org', 'wikidata.org', 'wikimedia.org', 'wikinews.org',
        'wikipedia.org', 'wikisource.org', 'wikiversity.org',
        'wikivoyage.org', 'wiktionary.org', 'windowsupdate.com',
        'withgoogle.com', 'withyoutube.com', 'wordpress', 'worldsecuresystems.com',
        'x.company', 'youtu', 'youtube', 'yt.be', 'ytimg.com',
        'zoom', 'zoomify.com', 'zynamics.com'
    ];

    // 检查域名匹配
    for (var i = 0; i < domainPatterns.length; i++) {
        if (url.indexOf(domainPatterns[i]) > 0) {
            return socksProxy;
        }
    }

    // Adobe相关域名（单独处理）
    var adobePatterns = [
        'lm.licenses.adobe.com', 'resources.licenses.adobe.com', 'cs.licenses.adobe.com',
        'exception.licenses.adobe.com', 'pubcerts.licenses.adobe.com',
        'workflow.licenses.adobe.com', 'auth.services.adobe.com',
        'adminconsole.adobe.com', 'ccmdls.adobe.com', 'ccmdl.adobe.com',
        'ans.oobesaas.adobe.com', 'ars.oobesaas.adobe.com',
        'cdn-ffc.oobesaas.adobe.com', 'ffc-icons.oobesaas.adobe.com',
        'ffc-static-cdn.oobesaas.adobe.com', 'prod-rel-ffc-ccm.oobesaas.adobe.com',
        'acc.adobeoobe.com', 'prod.acp.adobeoobe.com',
        'mir-s3-cdn-cf.behance.net', 'swupmf.adobe.com',
        'swupdl.adobe.com', 'oobe.adobe.com', 'productrouter.adobe.com',
        'armdl.adobe.com', 'armmf.adobe.com', 'ardownload.adobe.com',
        'ardownload2.adobe.com', 'agsupdate.adobe.com', 'ims-na1.adobelogin.com',
        'ims-prod06.adobelogin.com', 'ims-prod07.adobelogin.com',
        'static.adobelogin.com', 'delegated.adobelogin.com',
        'adobeid.services.adobe.com', 'adobeid-na1.services.adobe.com',
        'federatedid-na1.services.adobe.com', 'na1e-acc.services.adobe.com',
        'na1e.services.adobe.com', 'na1r.services.adobe.com',
        'ad.adobe-identity.com', 'ids-proxy.account.adobe.com',
        'lcs-cops.adobe.io', 'lcs-robs.adobe.io', 'lcs-entitlement.adobe.io',
        'lcs-ulecs.adobe.io', 'ams.adobe.com', 'adobelogin.prod.ims.adobejanus.com',
        'services.prod.ims.adobejanus.com', 'www-prod.adobesunbreak.com',
        'api-cna01.adobe-services.com', 'supportanyware.adobe.io',
        'genuine.adobe.com', 'prod.adobegenuine.com', 'gocart-web-prod-*.elb.amazonaws.com',
        'adobe-voice.adobe.io', 'cai.adobe.io', 'policy.adobe.io',
        'cai-manifests.adobe.com', 'creative.adobe.com', 'express.adobe.com',
        'color.adobe.com', 'store.adobe.com', 'store2.adobe.com',
        'store3.adobe.com', 'photoshop.com', 'adobe.com', 'adobe.io'
    ];

    for (var j = 0; j < adobePatterns.length; j++) {
        if (url.indexOf(adobePatterns[j]) > 0) {
            return socksProxy;
        }
    }

    return 'DIRECT';
}
