import asyncio, httpx, ddddocr, os

def encode_credentials(username, password, scode, sxh):
    code = username + "%%%" + password
    encoded = ""
    for i in range(min(len(code), 20)):
        n = int(sxh[i])
        encoded += code[i] + scode[:n]
        scode = scode[n:]
    if len(code) > 20:
        encoded += code[20:]
    return encoded

async def test_and_save_homepage():
    username = "202202140215"
    password = "123@Kongchen"
    
    s = httpx.AsyncClient(timeout=30, follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
    
    # Step 1: Get login page
    await s.get("http://xk.csust.edu.cn/")
    print("✅ 1. 获取登录页面成功")
    
    # Step 2: Get captcha and OCR
    captcha = await s.get("http://xk.csust.edu.cn/verifycode.servlet")
    ocr = ddddocr.DdddOcr(show_ad=False)
    code = ocr.classification(captcha.content)
    print(f"✅ 2. OCR识别验证码: [{code}]")
    
    # Step 3: Get encryption key
    sess_resp = await s.post("http://xk.csust.edu.cn/Logon.do?method=logon&flag=sess")
    parts = sess_resp.text.strip().split("#")
    scode, sxh = parts[0], parts[1]
    encoded = encode_credentials(username, password, scode, sxh)
    print(f"✅ 3. 获取密钥并加密凭证完成")
    
    # Step 4: Login - disable redirects to see if login succeeds
    login_data = {"userAccount": "", "userPassword": "", "RANDOMCODE": code, "encoded": encoded}
    # Disable redirects to check the actual login response
    s_no_redirect = httpx.AsyncClient(timeout=30, follow_redirects=False,
        headers={"User-Agent": "Mozilla/5.0"}, cookies=s.cookies)
    
    login_resp = await s_no_redirect.post("http://xk.csust.edu.cn/Logon.do?method=logon", data=login_data)
    print(f"✅ 4. 登录请求完成, 状态码: {login_resp.status_code}")
    
    # Check if redirected (302)
    if login_resp.status_code == 302:
        redirect_url = login_resp.headers.get("Location", "")
        print(f"   登录成功! 重定向到: {redirect_url}")
        
        # Merge cookies from login response
        for cookie in login_resp.cookies.jar:
            s.cookies.set(cookie.name, cookie.value)
        
        # Follow redirect manually
        if redirect_url:
            home_resp = await s.get("http://xk.csust.edu.cn" + redirect_url if redirect_url.startswith("/") else redirect_url)
            print(f"✅ 5. 访问重定向页面成功")
            
            # Now get the actual student main page
            main_resp = await s.get("http://xk.csust.edu.cn/jsxsd/framework/xsMain.jsp")
            print(f"✅ 6. 获取学生主页成功")
            
            # Save to file
            file_path = os.path.join(os.getcwd(), "教务系统主页.html")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(main_resp.text)
            print(f"✅ 7. 主页已保存到: {file_path}")
            
            # Verify it's not login page
            if "登录" not in main_resp.text or "学生" in main_resp.text or "课表" in main_resp.text:
                print("🎉 确认：登录成功，已获取学生主页!")
            else:
                print("⚠️ 警告：页面仍显示登录页，可能会话失效")
                
            await s_no_redirect.aclose()
            await s.aclose()
            return file_path
    else:
        print(f"❌ 登录失败，状态码: {login_resp.status_code}")
        await s_no_redirect.aclose()
        await s.aclose()
        return None

if __name__ == "__main__":
    file = asyncio.run(test_and_save_homepage())
    if file:
        print(f"\n请打开文件查看登录结果: {file}")
