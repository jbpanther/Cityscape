//
//  LoginView.swift
//  Cityscape
//
//  Created by Jackson Butler on 11/30/25.
//  Rewritten during Phase B of the Firebase → Supabase migration.
//
//  Authentication flow:
//  - Sign up: creates a Supabase user and (because email confirmation is on
//    in the Supabase Dashboard) sends a confirmation email. The user must
//    click the link before they can log in. We show a "check your email"
//    alert and don't navigate anywhere.
//  - Log in: succeeds only if the account exists AND the email is confirmed.
//    On success, the Supabase SDK persists the session to the Keychain, so
//    on next app launch we can skip the login screen.
//  - Restore: on appear, if a persisted session exists, jump straight to
//    the map — same behavior as before.
//

import SwiftUI
import Supabase

struct LoginView: View {
    enum Field {
        case email, password
    }

    @State private var email = ""
    @State private var password = ""
    @State private var showingAlert = false
    @State private var alertMessage = ""
    @State private var buttonsDisabled = true
    @State private var presentSheet = false
    @FocusState private var focusField: Field?

    var body: some View {
        VStack {
            Image("logoalt")
                .resizable()
                .scaledToFit()
                .padding()

            Group {
                TextField("E-mail", text: $email)
                    .keyboardType(.emailAddress)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                    .submitLabel(.next)
                    .focused($focusField, equals: .email)
                    .onSubmit {
                        focusField = .password
                    }
                    .onChange(of: email) {
                        enableButtons()
                    }

                SecureField("Password", text: $password)
                    .textInputAutocapitalization(.never)
                    .submitLabel(.done)
                    .focused($focusField, equals: .password)
                    .onSubmit {
                        focusField = nil
                    }
                    .onChange(of: password) {
                        enableButtons()
                    }
            }
            .textFieldStyle(.roundedBorder)
            .overlay {
                RoundedRectangle(cornerRadius: 5)
                    .stroke(.gray.opacity(0.5), lineWidth: 2)
            }
            .padding(.horizontal)

            HStack {
                Button {
                    register()
                } label: {
                    Text("Sign Up")
                }
                .padding(.trailing)

                Button {
                    login()
                } label: {
                    Text("Log In")
                }
                .padding(.leading)
            }
            .disabled(buttonsDisabled)
            .buttonStyle(.borderedProminent)
            .font(.title2)
            .padding(.top)
        }
        .alert(alertMessage, isPresented: $showingAlert) {
            Button("OK", role: .cancel) {}
        }
        .onAppear {
            // Supabase SDK persists sessions to Keychain automatically; if one
            // exists, we skip straight to the map.
            if SupabaseManager.shared.auth.currentUser != nil {
                print("🪵 Restored existing Supabase session")
                presentSheet = true
            }
        }
        .fullScreenCover(isPresented: $presentSheet) {
            MapView()
        }
    }

    func clearFields() {
        email = ""
        password = ""
    }

    func enableButtons() {
        let emailIsGood = email.count >= 6 && email.contains("@")
        let passwordIsGood = password.count >= 6
        buttonsDisabled = !(emailIsGood && passwordIsGood)
    }

    func register() {
        // Capture the entered email so we can show it in the confirmation
        // notice even after we clear the fields.
        let attemptedEmail = email

        Task {
            do {
                let response = try await SupabaseManager.shared.auth.signUp(
                    email: email,
                    password: password
                )

                // With email confirmation ON, signUp returns a user but no
                // session — Supabase is waiting for the user to click the
                // confirmation link before they can log in.
                if response.session == nil {
                    print("📬 Confirmation email sent to \(attemptedEmail)")
                    alertMessage = "Confirmation email sent to \(attemptedEmail). Click the link in the email, then come back and log in."
                    showingAlert = true
                    clearFields()
                } else {
                    // This path fires if confirmation gets turned off later
                    // in the Supabase Dashboard — user is instantly logged in.
                    print("😎 Registration + auto-login success!")
                    clearFields()
                    presentSheet = true
                }
            } catch {
                print("😡 SIGN-UP ERROR: \(error.localizedDescription)")
                alertMessage = "SIGN-UP ERROR: \(error.localizedDescription)"
                showingAlert = true
            }
        }
    }

    func login() {
        Task {
            do {
                _ = try await SupabaseManager.shared.auth.signIn(
                    email: email,
                    password: password
                )
                print("🪵 Login Successful!")
                clearFields()
                presentSheet = true
            } catch {
                // Supabase surfaces "Email not confirmed" here if the user
                // hasn't clicked the link yet — the error message is
                // human-readable so we just pass it through.
                print("😡 LOGIN ERROR: \(error.localizedDescription)")
                alertMessage = "LOGIN ERROR: \(error.localizedDescription)"
                showingAlert = true
            }
        }
    }
}


#Preview {
    LoginView()
}
