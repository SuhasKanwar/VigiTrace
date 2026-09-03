import { Router } from "express";
import { googleAuthHandler, signInHandler, signOutHandler, signUpHandler } from "../controllers/authController.js";

const authRouter = Router();

authRouter.post("/signup", signUpHandler);
authRouter.post("/google", googleAuthHandler);
authRouter.post("/signin", signInHandler);
authRouter.post("/signout", signOutHandler);

export default authRouter;