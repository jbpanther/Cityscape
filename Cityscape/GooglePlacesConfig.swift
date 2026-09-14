//
//  GooglePlacesConfig.swift
//  Hackathon
//
//  Created by Jackson Butler on 12/1/25.
//

import Foundation
import GooglePlacesSwift

enum GooglePlacesConfig {
    static func configure() {
        if !PlacesClient.provideAPIKey(Secrets.googleMapsAPIKey) {
            NSLog("PLACES: SDK rejected the API key — place search will not work.")
        }
    }
}
